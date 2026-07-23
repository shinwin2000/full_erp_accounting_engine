# AUTO-GENERATED TESTS for policy_engine/psak/psak_02_cash_flow.py
# =========================================
# Regenerated with meaningful assertions.

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from policy_engine.psak.psak_02_cash_flow import (
    PSAK2,
    CashFlowActivity,
    CashFlowItem,
    CashFlowMethod,
    CashFlowStatement,
    PSAK2CashFlowService,
    PSAK2ComplianceLevel,
    PSAK2Error,
    PSAK2Rules,
    PSAK2ValidationError,
    PSAK2ValidationResult,
    PSAK2Validator,
    get_psak2_validator,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------
@pytest.fixture
def validator():
    """Return a fresh PSAK2Validator instance."""
    return PSAK2Validator()


@pytest.fixture
def sample_statement(validator):
    """Create a basic cash flow statement with some items."""
    entity_id = uuid4()
    stmt = validator.create_statement(
        entity_id=entity_id,
        entity_name="PT ABC",
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 12, 31, tzinfo=UTC),
        method=CashFlowMethod.DIRECT,
        currency="IDR",
    )
    # Add operating items
    stmt = validator.add_item(
        stmt, "Penerimaan dari pelanggan", Decimal("1000000000"),
        CashFlowActivity.OPERATING, True
    )
    stmt = validator.add_item(
        stmt, "Pembayaran ke pemasok", Decimal("600000000"),
        CashFlowActivity.OPERATING, False
    )
    stmt = validator.add_item(
        stmt, "Pembayaran gaji", Decimal("200000000"),
        CashFlowActivity.OPERATING, False
    )
    # Investing
    stmt = validator.add_item(
        stmt, "Pembelian aset tetap", Decimal("300000000"),
        CashFlowActivity.INVESTING, False
    )
    # Financing
    stmt = validator.add_item(
        stmt, "Pinjaman bank", Decimal("500000000"),
        CashFlowActivity.FINANCING, True
    )
    stmt = validator.add_item(
        stmt, "Pembayaran dividen", Decimal("100000000"),
        CashFlowActivity.FINANCING, False
    )
    stmt = validator.set_beginning_cash(stmt, Decimal("50000000"))
    stmt = validator.set_ending_cash(stmt, Decimal("50000000") + stmt.net_increase_decrease())
    stmt = validator.add_non_cash_transaction(stmt, "Akuisisi bangunan dengan menerbitkan saham")
    return stmt


# -----------------------------------------------------------------------------
# Enum tests
# -----------------------------------------------------------------------------
class TestCashFlowActivity:
    def test_members_exist(self):
        assert hasattr(CashFlowActivity, "OPERATING")
        assert hasattr(CashFlowActivity, "INVESTING")
        assert hasattr(CashFlowActivity, "FINANCING")

    def test_member_is_instance(self):
        assert isinstance(CashFlowActivity.OPERATING, CashFlowActivity)


class TestCashFlowMethod:
    def test_members_exist(self):
        assert hasattr(CashFlowMethod, "DIRECT")
        assert hasattr(CashFlowMethod, "INDIRECT")

    def test_member_is_instance(self):
        assert isinstance(CashFlowMethod.DIRECT, CashFlowMethod)


class TestPSAK2ComplianceLevel:
    def test_members_exist(self):
        assert hasattr(PSAK2ComplianceLevel, "FULL")
        assert hasattr(PSAK2ComplianceLevel, "SUBSTANTIAL")
        assert hasattr(PSAK2ComplianceLevel, "PARTIAL")
        assert hasattr(PSAK2ComplianceLevel, "NON_COMPLIANT")

    def test_member_is_instance(self):
        assert isinstance(PSAK2ComplianceLevel.FULL, PSAK2ComplianceLevel)


# -----------------------------------------------------------------------------
# Exception tests
# -----------------------------------------------------------------------------
class TestPSAK2Error:
    def test_construction(self):
        exc = PSAK2Error("Test error")
        assert isinstance(exc, PSAK2Error)
        assert str(exc) == "Test error"


class TestPSAK2ValidationError:
    def test_construction(self):
        exc = PSAK2ValidationError("Validation error")
        assert isinstance(exc, PSAK2ValidationError)
        assert str(exc) == "Validation error"


# -----------------------------------------------------------------------------
# Data Classes
# -----------------------------------------------------------------------------
class TestCashFlowItem:
    def test_net_amount_inflow(self):
        item = CashFlowItem(
            description="Sales",
            amount=Decimal("1000"),
            activity=CashFlowActivity.OPERATING,
            is_inflow=True,
        )
        assert item.net_amount == Decimal("1000")

    def test_net_amount_outflow(self):
        item = CashFlowItem(
            description="Purchase",
            amount=Decimal("500"),
            activity=CashFlowActivity.OPERATING,
            is_inflow=False,
        )
        assert item.net_amount == Decimal("-500")

    def test_to_dict(self):
        item = CashFlowItem(
            description="Interest received",
            amount=Decimal("200"),
            activity=CashFlowActivity.INVESTING,
            is_inflow=True,
            tax_effect=Decimal("20"),
            related_item_id=uuid4(),
        )
        data = item.to_dict()
        assert data["description"] == "Interest received"
        assert data["amount"] == "200"
        assert data["activity"] == "investasi"
        assert data["is_inflow"] is True
        assert data["net_amount"] == "200"
        assert data["tax_effect"] == "20"


class TestCashFlowStatement:
    def test_total_by_activity(self, sample_statement):
        stmt = sample_statement
        # Operating total: 1,000,000,000 - 600,000,000 - 200,000,000 = 200,000,000
        assert stmt.total_by_activity(CashFlowActivity.OPERATING) == Decimal("200000000")
        # Investing: -300,000,000
        assert stmt.total_by_activity(CashFlowActivity.INVESTING) == Decimal("-300000000")
        # Financing: 500,000,000 - 100,000,000 = 400,000,000
        assert stmt.total_by_activity(CashFlowActivity.FINANCING) == Decimal("400000000")

    def test_net_cash_operating(self, sample_statement):
        assert sample_statement.net_cash_operating() == Decimal("200000000")

    def test_net_cash_investing(self, sample_statement):
        assert sample_statement.net_cash_investing() == Decimal("-300000000")

    def test_net_cash_financing(self, sample_statement):
        assert sample_statement.net_cash_financing() == Decimal("400000000")

    def test_net_increase_decrease(self, sample_statement):
        expected = Decimal("200000000") - Decimal("300000000") + Decimal("400000000")
        assert sample_statement.net_increase_decrease() == expected

    def test_reconcile_cash_true(self, sample_statement):
        assert sample_statement.reconcile_cash() is True

    def test_reconcile_cash_false(self, validator):
        stmt = validator.create_statement(uuid4(), "Test", datetime.now(UTC), datetime.now(UTC))
        stmt = validator.set_beginning_cash(stmt, Decimal("100"))
        stmt = validator.set_ending_cash(stmt, Decimal("200"))
        # No items, net increase = 0, so 100 != 200
        assert stmt.reconcile_cash() is False

    def test_to_dict(self, sample_statement):
        data = sample_statement.to_dict()
        assert data["entity_name"] == "PT ABC"
        assert data["method"] == "langsung"
        assert data["net_operating"] == "200000000"
        assert data["net_investing"] == "-300000000"
        assert data["net_financing"] == "400000000"
        assert data["reconciles"] is True
        assert len(data["items"]) == 6
        assert len(data["non_cash_transactions"]) == 1


class TestPSAK2ValidationResult:
    def test_initial_state(self):
        result = PSAK2ValidationResult(
            is_compliant=True,
            compliance_level=PSAK2ComplianceLevel.FULL
        )
        assert result.is_compliant is True
        assert result.compliance_level == PSAK2ComplianceLevel.FULL
        assert result.errors == []
        assert result.warnings == []
        assert result.hash_sha256 != ""

    def test_add_error(self):
        result = PSAK2ValidationResult(
            is_compliant=True,
            compliance_level=PSAK2ComplianceLevel.FULL
        )
        result.add_error("Classification error")
        assert result.is_compliant is False
        assert result.compliance_level == PSAK2ComplianceLevel.NON_COMPLIANT
        assert "Classification error" in result.errors

    def test_add_warning(self):
        result = PSAK2ValidationResult(
            is_compliant=True,
            compliance_level=PSAK2ComplianceLevel.FULL
        )
        result.add_warning("Disclosure missing")
        assert result.is_compliant is True
        assert result.compliance_level == PSAK2ComplianceLevel.SUBSTANTIAL
        assert "Disclosure missing" in result.warnings

    def test_add_warning_already_substantial(self):
        result = PSAK2ValidationResult(
            is_compliant=True,
            compliance_level=PSAK2ComplianceLevel.SUBSTANTIAL
        )
        result.add_warning("Another warning")
        assert result.compliance_level == PSAK2ComplianceLevel.SUBSTANTIAL  # unchanged

    def test_to_dict(self):
        result = PSAK2ValidationResult(
            is_compliant=False,
            compliance_level=PSAK2ComplianceLevel.NON_COMPLIANT,
            errors=["Error1"],
            warnings=["Warning1"],
        )
        data = result.to_dict()
        assert data["is_compliant"] is False
        assert data["compliance_level"] == "tidak_patuh"
        assert data["errors"] == ["Error1"]
        assert data["warnings"] == ["Warning1"]


# -----------------------------------------------------------------------------
# Domain Services
# -----------------------------------------------------------------------------
class TestPSAK2CashFlowService:
    def test_indirect_method_basic(self):
        net_profit = Decimal("100000000")
        adjustments = {
            "depreciation": Decimal("20000000"),
            "amortization": Decimal("5000000"),
        }
        wc_changes = {
            "increase_receivables": Decimal("-10000000"),
            "decrease_inventory": Decimal("5000000"),
        }
        tax_paid = Decimal("15000000")
        interest_paid = Decimal("5000000")
        result = PSAK2CashFlowService.indirect_method(
            net_profit, adjustments, wc_changes, tax_paid, interest_paid
        )
        # 100M + (20M+5M) + (-10M+5M) - 15M - 5M = 100M + 25M - 5M - 20M = 100M
        assert result == Decimal("100000000")

    def test_indirect_method_no_adjustments(self):
        result = PSAK2CashFlowService.indirect_method(
            net_profit=Decimal("50000000"),
            adjustments={},
            changes_in_working_capital={},
            tax_paid=Decimal("0"),
            interest_paid=Decimal("0"),
        )
        assert result == Decimal("50000000")

    def test_direct_method(self):
        receipts = Decimal("900000000")
        suppliers = Decimal("500000000")
        employees = Decimal("150000000")
        other = Decimal("50000000")
        tax = Decimal("30000000")
        interest = Decimal("10000000")
        result = PSAK2CashFlowService.direct_method(
            receipts, suppliers, employees, other, tax, interest
        )
        # 900M - 500M - 150M - 50M - 30M - 10M = 160M
        assert result == Decimal("160000000")

    def test_cash_flows_from_investing(self):
        proceeds_sale = Decimal("80000000")
        purchase_assets = Decimal("200000000")
        proceeds_inv_sale = Decimal("30000000")
        purchase_inv = Decimal("100000000")
        result = PSAK2CashFlowService.cash_flows_from_investing(
            proceeds_sale, purchase_assets, proceeds_inv_sale, purchase_inv
        )
        # 80M + 30M - 200M - 100M = -190M
        assert result == Decimal("-190000000")

    def test_cash_flows_from_financing(self):
        issuance = Decimal("150000000")
        loans = Decimal("300000000")
        repayment = Decimal("120000000")
        dividends = Decimal("60000000")
        result = PSAK2CashFlowService.cash_flows_from_financing(
            issuance, loans, repayment, dividends
        )
        # 150M + 300M - 120M - 60M = 270M
        assert result == Decimal("270000000")


# -----------------------------------------------------------------------------
# Rules
# -----------------------------------------------------------------------------
class TestPSAK2Rules:
    def test_validate_classification_operating_asset_purchase_error(self):
        items = [
            CashFlowItem(
                description="Pembelian aset tetap",
                amount=Decimal("100000"),
                activity=CashFlowActivity.OPERATING,
                is_inflow=False,
            )
        ]
        result = PSAK2Rules.validate_classification(items)
        assert result.is_compliant is False
        assert result.compliance_level == PSAK2ComplianceLevel.NON_COMPLIANT
        assert any("seharusnya diklasifikasikan sebagai investasi" in e for e in result.errors)

    def test_validate_classification_investing_dividend_warning(self):
        items = [
            CashFlowItem(
                description="Dividen diterima",
                amount=Decimal("5000"),
                activity=CashFlowActivity.INVESTING,
                is_inflow=True,
            )
        ]
        result = PSAK2Rules.validate_classification(items)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK2ComplianceLevel.SUBSTANTIAL
        assert any("Dividen diterima" in w for w in result.warnings)

    def test_validate_disclosure_reconciles_true(self, sample_statement):
        result = PSAK2Rules.validate_disclosure(sample_statement)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK2ComplianceLevel.FULL
        assert result.errors == []

    def test_validate_disclosure_reconciles_false(self, validator):
        stmt = validator.create_statement(uuid4(), "Test", datetime.now(UTC), datetime.now(UTC))
        stmt = validator.set_beginning_cash(stmt, Decimal("100"))
        stmt = validator.set_ending_cash(stmt, Decimal("200"))
        result = PSAK2Rules.validate_disclosure(stmt)
        assert result.is_compliant is False
        assert result.compliance_level == PSAK2ComplianceLevel.NON_COMPLIANT
        assert "Perubahan kas tidak sesuai dengan total arus kas" in result.errors

    def test_validate_disclosure_no_non_cash_warning(self, validator):
        stmt = validator.create_statement(
            uuid4(), "Test", datetime.now(UTC), datetime.now(UTC),
            method=CashFlowMethod.DIRECT
        )
        stmt = validator.set_beginning_cash(stmt, Decimal("0"))
        stmt = validator.set_ending_cash(stmt, Decimal("0"))
        result = PSAK2Rules.validate_disclosure(stmt)
        # It will also have reconcile error because ending=0 but net=0, so reconcile is true (0+0=0)
        # But no non-cash transactions -> warning
        assert result.is_compliant is True  # no error, just warning
        assert result.compliance_level == PSAK2ComplianceLevel.SUBSTANTIAL
        assert "Transaksi non-kas tidak diungkapkan" in result.warnings

    def test_validate_method_consistency_same(self):
        result = PSAK2Rules.validate_method_consistency(
            previous_method=CashFlowMethod.DIRECT,
            current_method=CashFlowMethod.DIRECT,
        )
        assert result.is_compliant is True
        assert result.compliance_level == PSAK2ComplianceLevel.FULL
        assert result.warnings == []

    def test_validate_method_consistency_different(self):
        result = PSAK2Rules.validate_method_consistency(
            previous_method=CashFlowMethod.DIRECT,
            current_method=CashFlowMethod.INDIRECT,
        )
        assert result.is_compliant is True
        assert result.compliance_level == PSAK2ComplianceLevel.SUBSTANTIAL
        assert "Perubahan metode penyajian arus kas" in result.warnings[0]


# -----------------------------------------------------------------------------
# Validator
# -----------------------------------------------------------------------------
class TestPSAK2Validator:
    def test_create_statement(self, validator):
        entity_id = uuid4()
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 12, 31, tzinfo=UTC)
        stmt = validator.create_statement(
            entity_id=entity_id,
            entity_name="PT XYZ",
            period_start=start,
            period_end=end,
            method=CashFlowMethod.INDIRECT,
            currency="USD",
        )
        assert isinstance(stmt, CashFlowStatement)
        assert stmt.entity_id == entity_id
        assert stmt.entity_name == "PT XYZ"
        assert stmt.period_start == start
        assert stmt.period_end == end
        assert stmt.method == CashFlowMethod.INDIRECT
        assert stmt.currency == "USD"
        assert stmt.statement_id is not None
        assert stmt.items == []
        assert stmt.beginning_cash == Decimal("0")
        assert stmt.ending_cash == Decimal("0")
        assert stmt.non_cash_transactions == []

    def test_add_item(self, validator):
        stmt = validator.create_statement(uuid4(), "Test", datetime.now(UTC), datetime.now(UTC))
        stmt = validator.add_item(
            stmt, "Receipts", Decimal("1000"), CashFlowActivity.OPERATING, True, tax_effect=Decimal("100")
        )
        assert len(stmt.items) == 1
        item = stmt.items[0]
        assert item.description == "Receipts"
        assert item.amount == Decimal("1000")
        assert item.activity == CashFlowActivity.OPERATING
        assert item.is_inflow is True
        assert item.tax_effect == Decimal("100")

    def test_set_beginning_cash(self, validator):
        stmt = validator.create_statement(uuid4(), "Test", datetime.now(UTC), datetime.now(UTC))
        new_stmt = validator.set_beginning_cash(stmt, Decimal("50000"))
        assert new_stmt.beginning_cash == Decimal("50000")
        # Other fields unchanged
        assert new_stmt.entity_name == stmt.entity_name

    def test_set_ending_cash(self, validator):
        stmt = validator.create_statement(uuid4(), "Test", datetime.now(UTC), datetime.now(UTC))
        new_stmt = validator.set_ending_cash(stmt, Decimal("75000"))
        assert new_stmt.ending_cash == Decimal("75000")

    def test_add_non_cash_transaction(self, validator):
        stmt = validator.create_statement(uuid4(), "Test", datetime.now(UTC), datetime.now(UTC))
        stmt = validator.add_non_cash_transaction(stmt, "Akuisisi tanah dengan saham")
        assert len(stmt.non_cash_transactions) == 1
        assert stmt.non_cash_transactions[0] == "Akuisisi tanah dengan saham"
        # Adding another
        stmt = validator.add_non_cash_transaction(stmt, "Pengalihan hutang ke modal")
        assert len(stmt.non_cash_transactions) == 2

    def test_validate_statement_full_compliant(self, sample_statement):
        result = validator.validate_statement(sample_statement)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK2ComplianceLevel.FULL
        assert result.errors == []
        assert result.warnings == []  # because non-cash transactions exist

    def test_validate_statement_classification_error(self, validator):
        stmt = validator.create_statement(uuid4(), "Test", datetime.now(UTC), datetime.now(UTC))
        stmt = validator.add_item(
            stmt, "Pembelian aset tetap", Decimal("100000"), CashFlowActivity.OPERATING, False
        )
        stmt = validator.set_beginning_cash(stmt, Decimal("0"))
        stmt = validator.set_ending_cash(stmt, Decimal("-100000"))
        result = validator.validate_statement(stmt)
        # Should have classification error and reconciliation error (because net change = -100000, ending= -100000? Actually beginning=0, net=-100000, ending=-100000, so reconciles)
        # Actually net_increase = -100000, ending = -100000 -> reconciles. So only classification error.
        assert result.is_compliant is False
        assert result.compliance_level == PSAK2ComplianceLevel.NON_COMPLIANT
        assert any("seharusnya diklasifikasikan sebagai investasi" in e for e in result.errors)

    def test_get_requirements_summary(self, validator):
        summary = validator.get_requirements_summary()
        assert "activities" in summary
        assert "methods" in summary
        assert "required_disclosures" in summary
        assert "Operasi" in summary["activities"]
        assert "Langsung" in summary["methods"]
        assert len(summary["required_disclosures"]) >= 3


# -----------------------------------------------------------------------------
# PSAK2 Static Methods
# -----------------------------------------------------------------------------
class TestPSAK2:
    def test_get_allowed_methods(self):
        methods = PSAK2.get_allowed_methods()
        assert isinstance(methods, list)
        assert "langsung" in methods
        assert "tidak_langsung" in methods

    def test_validate_operating_cash_flow(self):
        result = PSAK2.validate_operating_cash_flow(Decimal("1000"))
        assert result is True


# -----------------------------------------------------------------------------
# Singleton accessor
# -----------------------------------------------------------------------------
def test_get_psak2_validator():
    v1 = get_psak2_validator()
    v2 = get_psak2_validator()
    assert v1 is v2
    assert isinstance(v1, PSAK2Validator)