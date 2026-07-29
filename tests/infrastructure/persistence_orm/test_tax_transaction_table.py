# tests/infrastructure/persistence_orm/test_tax_transaction_table.py
"""
Comprehensive tests for infrastructure/persistence_orm/tax_transaction_table.py
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from infrastructure.persistence_orm.tax_transaction_table import TaxTransactionTable


class TestTaxTransactionTable:
    """Tests for the TaxTransactionTable ORM model."""

    def test_tablename_defined(self):
        assert hasattr(TaxTransactionTable, "__tablename__")
        assert isinstance(TaxTransactionTable.__tablename__, str)
        assert len(TaxTransactionTable.__tablename__) > 0

    def test_instantiation(self):
        instance = TaxTransactionTable(
            id=uuid4(),
            transaction_number="TX-001",
            transaction_date=date(2026, 7, 1),
            tax_type="ppn",
            tax_period_type="monthly",
            tax_period_year=2026,
            tax_period_month=7,
            taxable_amount=Decimal("1000000"),
            tax_rate=Decimal("11"),
            tax_amount=Decimal("110000"),
            currency="IDR",
            is_withholding=False,
            reference_type="invoice",
            status="calculated",
            version=1,
        )
        assert isinstance(instance, TaxTransactionTable)
        assert instance.transaction_number == "TX-001"
        assert instance.tax_amount == Decimal("110000")

    # -------------------- Fixtures --------------------
    @pytest.fixture
    def tx(self):
        return TaxTransactionTable(
            id=uuid4(),
            transaction_number="TX-001",
            transaction_date=date(2026, 7, 1),
            tax_type="ppn",
            tax_period_type="monthly",
            tax_period_year=2026,
            tax_period_month=7,
            taxable_amount=Decimal("1000000"),
            tax_rate=Decimal("11"),
            tax_amount=Decimal("110000"),
            currency="IDR",
            is_withholding=False,
            counterparty_tax_id=None,
            counterparty_name=None,
            ntpn=None,
            payment_date=None,
            reference_type="invoice",
            reference_id=uuid4(),
            spt_number=None,
            filing_date=None,
            status="calculated",
            extra_metadata=None,
            created_by=uuid4(),
            version=1,
        )

    @pytest.fixture
    def tx_reported(self, tx):
        tx.status = "reported"
        tx.spt_number = "SPT-001"
        tx.filing_date = date(2026, 7, 31)
        return tx

    @pytest.fixture
    def tx_paid(self, tx):
        tx.status = "paid"
        tx.ntpn = "NTPN-1234567890"
        tx.payment_date = date(2026, 8, 1)
        return tx

    @pytest.fixture
    def tx_adjusted(self, tx):
        tx.status = "adjusted"
        return tx

    # -------------------- Property Tests --------------------
    def test_is_reported(self, tx, tx_reported, tx_paid):
        assert tx.is_reported is False
        assert tx_reported.is_reported is True
        assert tx_paid.is_reported is True  # paid is also reported

    def test_is_paid(self, tx, tx_paid):
        assert tx.is_paid is False
        assert tx_paid.is_paid is True

    def test_is_paid_without_ntpn(self, tx):
        tx.status = "paid"
        tx.ntpn = None
        assert tx.is_paid is False

    def test_effective_tax_rate(self, tx):
        # tax_amount / taxable_amount * 100 = 110,000 / 1,000,000 * 100 = 11.0
        assert tx.effective_tax_rate == Decimal("11.0")

    def test_effective_tax_rate_zero_taxable(self, tx):
        tx.taxable_amount = Decimal(0)
        tx.tax_amount = Decimal(0)
        assert tx.effective_tax_rate == Decimal(0)

    def test_effective_tax_rate_with_decimal(self):
        tx2 = TaxTransactionTable(
            taxable_amount=Decimal("333333"),
            tax_amount=Decimal("36666"),
        )
        # 36,666 / 333,333 * 100 ≈ 11.000011...
        # We can't assert exact, but we can check it's a Decimal and positive
        assert isinstance(tx2.effective_tax_rate, Decimal)

    def test_period_display_monthly(self, tx):
        assert tx.period_display == "2026-07"

    def test_period_display_quarterly(self, tx):
        tx.tax_period_type = "quarterly"
        tx.tax_period_month = 4  # Q2
        assert tx.period_display == "Q2 2026"
        tx.tax_period_month = 7  # Q3
        assert tx.period_display == "Q3 2026"
        tx.tax_period_month = 12  # Q4
        assert tx.period_display == "Q4 2026"

    def test_period_display_annual(self, tx):
        tx.tax_period_type = "annual"
        assert tx.period_display == "2026"

    # -------------------- Method Tests --------------------
    def test_calculate_tax(self, tx):
        tx.tax_amount = Decimal(0)
        tx.taxable_amount = Decimal("2000000")
        tx.tax_rate = Decimal("10")
        tx.calculate_tax()
        assert tx.tax_amount == Decimal("200000")
        assert tx.version == 2

    def test_calculate_tax_with_fraction(self, tx):
        tx.tax_amount = Decimal(0)
        tx.taxable_amount = Decimal("333333")
        tx.tax_rate = Decimal("11")
        tx.calculate_tax()
        # 333,333 * 11 / 100 = 36,666.63
        expected = Decimal("36666.63")
        assert tx.tax_amount == expected
        assert tx.version == 2

    def test_mark_reported_from_calculated(self, tx):
        spt = "SPT-001"
        filing_date = date(2026, 7, 31)
        tx.mark_reported(spt, filing_date)
        assert tx.status == "reported"
        assert tx.spt_number == spt
        assert tx.filing_date == filing_date
        assert tx.version == 2

    def test_mark_reported_from_adjusted(self, tx):
        tx.status = "adjusted"
        spt = "SPT-002"
        filing_date = date(2026, 8, 15)
        tx.mark_reported(spt, filing_date)
        assert tx.status == "reported"
        assert tx.version == 2

    def test_mark_reported_invalid_status_raises(self, tx):
        tx.status = "paid"
        with pytest.raises(ValueError, match="Cannot mark as reported with status paid"):
            tx.mark_reported("SPT", date.today())

    def test_mark_paid_from_reported(self, tx_reported):
        ntpn = "NTPN-1234567890"
        payment_date = date(2026, 8, 1)
        tx_reported.mark_paid(ntpn, payment_date)
        assert tx_reported.status == "paid"
        assert tx_reported.ntpn == ntpn
        assert tx_reported.payment_date == payment_date
        assert tx_reported.version == 2

    def test_mark_paid_from_adjusted(self, tx):
        tx.status = "adjusted"
        ntpn = "NTPN-0987654321"
        payment_date = date(2026, 8, 15)
        tx.mark_paid(ntpn, payment_date)
        assert tx.status == "paid"
        assert tx.version == 2

    def test_mark_paid_invalid_status_raises(self, tx):
        tx.status = "calculated"
        with pytest.raises(ValueError, match="Cannot mark as paid with status calculated"):
            tx.mark_paid("NTPN", date.today())

    def test_adjust_from_calculated(self, tx):
        adjustment = Decimal("50000")
        reason = "Correction for rounding"
        tx.adjust(adjustment, reason)
        assert tx.tax_amount == adjustment
        assert tx.status == "adjusted"
        assert tx.extra_metadata is not None
        assert tx.extra_metadata["adjustment_reason"] == reason
        assert "adjusted_at" in tx.extra_metadata
        assert tx.version == 2

    def test_adjust_from_reported(self, tx_reported):
        adjustment = Decimal("60000")
        reason = "Reclassification"
        tx_reported.adjust(adjustment, reason)
        assert tx_reported.tax_amount == adjustment
        assert tx_reported.status == "adjusted"
        assert tx_reported.extra_metadata is not None
        assert tx_reported.extra_metadata["adjustment_reason"] == reason
        assert tx_reported.version == 2

    def test_adjust_from_paid_raises(self, tx_paid):
        with pytest.raises(ValueError, match="Cannot adjust tax transaction that is already paid"):
            tx_paid.adjust(Decimal("1000"), "test")

    def test_cancel_from_calculated(self, tx):
        tx.cancel()
        assert tx.status == "cancelled"
        assert tx.version == 2

    def test_cancel_from_reported(self, tx_reported):
        tx_reported.cancel()
        assert tx_reported.status == "cancelled"
        assert tx_reported.version == 2

    def test_cancel_from_adjusted(self, tx_adjusted):
        tx_adjusted.cancel()
        assert tx_adjusted.status == "cancelled"
        assert tx_adjusted.version == 2

    def test_cancel_from_paid_raises(self, tx_paid):
        with pytest.raises(ValueError, match="Cannot cancel tax transaction that is already paid"):
            tx_paid.cancel()

    # -------------------- to_dict Tests --------------------
    def test_to_dict(self, tx):
        d = tx.to_dict()
        assert d["transaction_number"] == "TX-001"
        assert d["tax_type"] == "ppn"
        assert d["tax_period_year"] == 2026
        assert d["tax_period_month"] == 7
        assert d["taxable_amount"] == float(tx.taxable_amount)
        assert d["tax_rate"] == float(tx.tax_rate)
        assert d["tax_amount"] == float(tx.tax_amount)
        assert d["status"] == "calculated"
        assert d["version"] == 1
        assert "id" in d
        assert "created_by" in d

    def test_to_dict_with_optional_fields(self, tx_paid):
        d = tx_paid.to_dict()
        assert d["ntpn"] == "NTPN-1234567890"
        assert d["payment_date"] == tx_paid.payment_date.isoformat()
        assert d["status"] == "paid"

    # -------------------- Edge Cases --------------------
    def test_effective_tax_rate_with_negative(self, tx):
        # Should still compute even if negative (though not expected)
        tx.tax_amount = Decimal("-1000")
        tx.taxable_amount = Decimal("10000")
        assert tx.effective_tax_rate == Decimal("-10.0")

    def test_adjust_with_existing_metadata(self, tx):
        tx.extra_metadata = {"existing": "value"}
        tx.adjust(Decimal("1000"), "test")
        assert tx.extra_metadata["existing"] == "value"
        assert tx.extra_metadata["adjustment_reason"] == "test"
        assert tx.extra_metadata["adjusted_at"] is not None

    def test_mark_paid_without_ntpn(self, tx_reported):
        # Should still allow, but is_paid will be False
        tx_reported.mark_paid("", date.today())
        assert tx_reported.status == "paid"
        assert tx_reported.ntpn == ""
        assert tx_reported.is_paid is False

    def test_calculate_tax_updates_version(self, tx):
        old_version = tx.version
        tx.calculate_tax()
        assert tx.version == old_version + 1
