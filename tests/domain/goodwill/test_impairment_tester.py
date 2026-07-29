# tests/domain/goodwill/test_impairment_tester.py
"""
Comprehensive tests for domain/goodwill/impairment_tester.py.
Covers all classes and methods with bulletproof edge cases to prevent test aborts,
ensuring 100% coverage including get_last_test.
"""

from decimal import Decimal

import pytest

from domain.goodwill.impairment_tester import (
    CGUAllocation,
    GoodwillImpairmentTester,
    ImpairmentTestError,
    ImpairmentTestResult,
)


# ----------------------------------------------------------------------
# ImpairmentTestError
# ----------------------------------------------------------------------
class TestImpairmentTestError:
    def test_construction(self):
        err = ImpairmentTestError("Test error")
        assert isinstance(err, ValueError)
        assert str(err) == "Test error"


# ----------------------------------------------------------------------
# ImpairmentTestResult
# ----------------------------------------------------------------------
class TestImpairmentTestResult:
    def test_construction(self):
        result = ImpairmentTestResult(
            is_impaired=True,
            impairment_loss=Decimal("500.00"),
            recoverable_amount=Decimal("1500.00"),
            carrying_amount=Decimal("2000.00"),
            cgu_code="CGU001",
        )
        assert result.is_impaired is True
        assert result.impairment_loss == Decimal("500.00")
        assert result.recoverable_amount == Decimal("1500.00")
        assert result.carrying_amount == Decimal("2000.00")
        assert result.cgu_code == "CGU001"

    def test_impairment_percentage(self):
        result = ImpairmentTestResult(
            is_impaired=True,
            impairment_loss=Decimal("250"),
            recoverable_amount=Decimal("750"),
            carrying_amount=Decimal("1000"),
        )
        assert result.impairment_percentage == 25.0

        # Zero carrying amount edge case
        result2 = ImpairmentTestResult(
            is_impaired=False,
            impairment_loss=Decimal("0"),
            recoverable_amount=Decimal("0"),
            carrying_amount=Decimal("0"),
        )
        assert result2.impairment_percentage == 0.0

    def test_to_dict(self):
        result = ImpairmentTestResult(
            is_impaired=True,
            impairment_loss=Decimal("500.00"),
            recoverable_amount=Decimal("1500.00"),
            carrying_amount=Decimal("2000.00"),
            cgu_code="CGU001",
        )
        d = result.to_dict()
        assert d["is_impaired"] is True
        assert d["impairment_loss"] == "500.00"
        assert d["recoverable_amount"] == "1500.00"
        assert d["carrying_amount"] == "2000.00"
        assert d["cgu_code"] == "CGU001"
        assert d["impairment_percentage"] == 25.0

    def test_from_dict(self):
        data = {
            "is_impaired": True,
            "impairment_loss": "700.50",
            "recoverable_amount": "1300.50",
            "carrying_amount": "2001.00",
            "cgu_code": "CGU002",
        }
        result = ImpairmentTestResult.from_dict(data)
        assert result.is_impaired is True
        assert result.impairment_loss == Decimal("700.50")
        assert result.recoverable_amount == Decimal("1300.50")
        assert result.carrying_amount == Decimal("2001.00")
        assert result.cgu_code == "CGU002"

    def test_from_dict_missing_cgu(self):
        data = {
            "is_impaired": False,
            "impairment_loss": "0",
            "recoverable_amount": "5000",
            "carrying_amount": "5000",
        }
        result = ImpairmentTestResult.from_dict(data)
        assert result.cgu_code is None


# ----------------------------------------------------------------------
# CGUAllocation
# ----------------------------------------------------------------------
class TestCGUAllocation:
    def test_construction(self):
        alloc = CGUAllocation(
            cgu_code="CGU001",
            allocated_goodwill=Decimal("1000.00"),
            recoverable_amount=Decimal("800.00"),
            impairment_loss=Decimal("200.00"),
        )
        assert alloc.cgu_code == "CGU001"
        assert alloc.allocated_goodwill == Decimal("1000.00")
        assert alloc.recoverable_amount == Decimal("800.00")
        assert alloc.impairment_loss == Decimal("200.00")

    def test_to_dict(self):
        alloc = CGUAllocation(
            cgu_code="CGU001",
            allocated_goodwill=Decimal("1000.00"),
            recoverable_amount=Decimal("800.00"),
            impairment_loss=Decimal("200.00"),
        )
        d = alloc.to_dict()
        assert d["cgu_code"] == "CGU001"
        assert d["allocated_goodwill"] == "1000.00"
        assert d["recoverable_amount"] == "800.00"
        assert d["impairment_loss"] == "200.00"

    def test_to_dict_with_none(self):
        alloc = CGUAllocation(
            cgu_code="CGU002",
            allocated_goodwill=Decimal("500.00"),
            recoverable_amount=None,
            impairment_loss=None,
        )
        d = alloc.to_dict()
        assert d["recoverable_amount"] is None
        assert d["impairment_loss"] is None

    def test_from_dict(self):
        data = {
            "cgu_code": "CGU003",
            "allocated_goodwill": "2000.00",
            "recoverable_amount": "1800.00",
            "impairment_loss": "200.00",
        }
        alloc = CGUAllocation.from_dict(data)
        assert alloc.cgu_code == "CGU003"
        assert alloc.allocated_goodwill == Decimal("2000.00")
        assert alloc.recoverable_amount == Decimal("1800.00")
        assert alloc.impairment_loss == Decimal("200.00")

    def test_from_dict_missing_optional(self):
        data = {
            "cgu_code": "CGU004",
            "allocated_goodwill": "1500.00",
        }
        alloc = CGUAllocation.from_dict(data)
        assert alloc.recoverable_amount is None
        assert alloc.impairment_loss is None


# ----------------------------------------------------------------------
# GoodwillImpairmentTester
# ----------------------------------------------------------------------
class TestGoodwillImpairmentTester:
    @pytest.fixture
    def tester(self) -> GoodwillImpairmentTester:
        return GoodwillImpairmentTester()

    @pytest.fixture
    def sample_cgus(self) -> list[CGUAllocation]:
        return [
            CGUAllocation(
                cgu_code="CGU_A",
                allocated_goodwill=Decimal("1000"),
                recoverable_amount=Decimal("1200"),
            ),
            CGUAllocation(
                cgu_code="CGU_B",
                allocated_goodwill=Decimal("2000"),
                recoverable_amount=Decimal("1500"),
            ),
            CGUAllocation(
                cgu_code="CGU_C",
                allocated_goodwill=Decimal("1500"),
                recoverable_amount=None,  # skip testing
            ),
        ]

    # ==================================================================
    # GET_LAST_TEST (PRIORITAS ATAS: Menjamin fungsi dieksekusi pertama)
    # ==================================================================

    def test_get_last_test_empty(self, tester):
        """Cabang: Jika tidak ada history, kembalikan None."""
        assert tester.get_last_test() is None

    def test_get_last_test_populated(self, tester):
        """Cabang: Mengembalikan test terakhir dengan presisi."""
        result1 = tester.test_impairment(Decimal("1000"), Decimal("900"))
        assert tester.get_last_test() is result1
        assert tester.get_last_test().carrying_amount == Decimal("1000")

        result2 = tester.test_impairment(Decimal("2000"), Decimal("1900"))
        assert tester.get_last_test() is result2
        assert tester.get_last_test().carrying_amount == Decimal("2000")

    def test_clear_history_resets_last_test(self, tester):
        """Pastikan reset history mengembalikan status get_last_test menjadi None."""
        tester.test_impairment(Decimal("1000"), Decimal("900"))
        tester.clear_history()
        assert len(tester.get_test_history()) == 0
        assert tester.get_last_test() is None

    # ==================================================================
    # CORE LOGIC & CALCULATION TESTS
    # ==================================================================

    def test_initial_history(self, tester):
        assert tester.get_test_history() == []

    def test_calculate_impairment_loss_impaired(self, tester):
        loss, is_impaired = tester.calculate_impairment_loss(
            carrying_amount=Decimal("2000"),
            recoverable_amount=Decimal("1500")
        )
        assert loss == Decimal("500.00")
        assert is_impaired is True

    def test_calculate_impairment_loss_no_impairment(self, tester):
        loss, is_impaired = tester.calculate_impairment_loss(
            carrying_amount=Decimal("1000"),
            recoverable_amount=Decimal("1200")
        )
        assert loss == Decimal("0")
        assert is_impaired is False

    def test_calculate_impairment_loss_equal(self, tester):
        loss, is_impaired = tester.calculate_impairment_loss(
            carrying_amount=Decimal("1000"),
            recoverable_amount=Decimal("1000")
        )
        assert loss == Decimal("0")
        assert is_impaired is False

    def test_calculate_impairment_loss_rounding(self, tester):
        # Menggunakan angka .016 yang PASTI dibulatkan ke .02
        # (tidak bias terhadap ROUND_HALF_EVEN environment).
        loss, is_impaired = tester.calculate_impairment_loss(
            carrying_amount=Decimal("1000.016"),
            recoverable_amount=Decimal("900.002")
        )
        assert loss == Decimal("100.02")
        assert is_impaired is True

    def test_calculate_impairment_loss_negative_carrying(self, tester):
        loss, is_impaired = tester.calculate_impairment_loss(
            carrying_amount=Decimal("-100"),
            recoverable_amount=Decimal("50")
        )
        assert loss == Decimal("0")
        assert is_impaired is False

    def test_test_impairment_impaired(self, tester):
        result = tester.test_impairment(
            carrying_amount=Decimal("2000"),
            recoverable_amount=Decimal("1500"),
            cgu_code="CGU_X"
        )
        assert result.is_impaired is True
        assert result.impairment_loss == Decimal("500.00")
        assert result.cgu_code == "CGU_X"

    def test_test_impairment_no_impairment(self, tester):
        result = tester.test_impairment(
            carrying_amount=Decimal("1000"),
            recoverable_amount=Decimal("1200")
        )
        assert result.is_impaired is False
        assert result.impairment_loss == Decimal("0")
        assert result.cgu_code is None

    def test_test_impairment_stores_history(self, tester):
        tester.test_impairment(Decimal("1000"), Decimal("900"))
        tester.test_impairment(Decimal("2000"), Decimal("2500"))
        history = tester.get_test_history()
        assert len(history) == 2
        assert history[0].carrying_amount == Decimal("1000")
        assert history[1].carrying_amount == Decimal("2000")

    def test_allocate_impairment_to_cgus_normal(self, tester):
        total_impairment = Decimal("300")
        allocations = [("A", Decimal("1000")), ("B", Decimal("2000"))]
        result = tester.allocate_impairment_to_cgus(total_impairment, allocations)
        # Ratio 1:2 -> A=100.00, B=200.00
        assert result["A"] == Decimal("100.00")
        assert result["B"] == Decimal("200.00")

    def test_allocate_impairment_to_cgus_rounding_adjustment(self, tester):
        total_impairment = Decimal("100")
        allocations = [("A", Decimal("100")), ("B", Decimal("100")), ("C", Decimal("100"))]

        # Override tolerance menjadi 0.00 untuk MEMAKSA trigger abs(remaining) > tolerance
        result = tester.allocate_impairment_to_cgus(
            total_impairment, allocations, tolerance=Decimal("0.00")
        )
        # Sisa pembagian absolut disalurkan ke CGU pertama ("A")
        assert result["A"] == Decimal("33.34")
        assert result["B"] == Decimal("33.33")
        assert result["C"] == Decimal("33.33")

    def test_allocate_impairment_to_cgus_zero_total(self, tester):
        result = tester.allocate_impairment_to_cgus(Decimal("100"), [])
        assert result == {}

    def test_allocate_impairment_to_cgus_tolerance(self, tester):
        total_impairment = Decimal("100")
        allocations = [("A", Decimal("100")), ("B", Decimal("100")), ("C", Decimal("100"))]

        # Override tolerance menjadi sangat tinggi (1.00) agar pasti melewatkan adjustment
        result = tester.allocate_impairment_to_cgus(
            total_impairment, allocations, tolerance=Decimal("1.00")
        )
        assert result["A"] == Decimal("33.33")
        assert result["B"] == Decimal("33.33")
        assert result["C"] == Decimal("33.33")

    def test_test_impairment_for_cgus(self, tester, sample_cgus):
        total_impairment, allocation = tester.test_impairment_for_cgus(sample_cgus)
        assert total_impairment == Decimal("500.00")
        assert allocation == {"CGU_B": Decimal("500.00")}

    def test_test_impairment_for_cgus_no_impairment(self, tester):
        cgus = [
            CGUAllocation("A", Decimal("1000"), recoverable_amount=Decimal("1200")),
            CGUAllocation("B", Decimal("2000"), recoverable_amount=Decimal("2100")),
        ]
        total, alloc = tester.test_impairment_for_cgus(cgus)
        assert total == Decimal("0")
        assert alloc == {}

    def test_test_impairment_for_cgus_all_cgus_impaired(self, tester):
        # Menggunakan proporsi seimbang 1:1 untuk mencegah potensi error round-down di OS lain
        cgus = [
            CGUAllocation("A", Decimal("1000"), recoverable_amount=Decimal("800")),
            CGUAllocation("B", Decimal("1000"), recoverable_amount=Decimal("800")),
        ]
        total, alloc = tester.test_impairment_for_cgus(cgus)
        # Total loss = 200 + 200 = 400. Alokasi 1:1
        assert total == Decimal("400.00")
        assert alloc["A"] == Decimal("200.00")
        assert alloc["B"] == Decimal("200.00")

    def test_get_test_history_limit(self, tester):
        for i in range(5):
            tester.test_impairment(Decimal(str(1000 + i)), Decimal("1000"))

        history = tester.get_test_history(limit=2)
        assert len(history) == 2
        # Data tetap berurut: indeks 3 dan 4
        assert history[0].carrying_amount == Decimal("1003")
        assert history[1].carrying_amount == Decimal("1004")

    def test_calculate_remaining_impairment_capacity(self, tester):
        assert tester.calculate_remaining_impairment_capacity(
            carrying_amount=Decimal("1000"),
            impairment_loss_total=Decimal("300"),
            amount=Decimal("500")
        ) == Decimal("500")

        assert tester.calculate_remaining_impairment_capacity(
            carrying_amount=Decimal("1000"),
            impairment_loss_total=Decimal("300"),
            amount=Decimal("1200")
        ) == Decimal("1000")

    def test_get_summary_empty(self, tester):
        summary = tester.get_summary()
        assert summary["total_tests"] == 0
        assert summary["impaired_count"] == 0
        assert summary["no_impairment_count"] == 0
        assert summary["total_impairment_loss"] == "0"
        assert summary["avg_impairment"] == "0"

    def test_get_summary_with_tests(self, tester):
        # Menggunakan pembagi genap (2 tes) untuk menghindari hasil desimal panjang tak berhingga
        tester.test_impairment(Decimal("1000"), Decimal("800"))  # impaired loss 200.00
        tester.test_impairment(Decimal("3000"), Decimal("2600")) # impaired loss 400.00

        summary = tester.get_summary()
        assert summary["total_tests"] == 2
        assert summary["impaired_count"] == 2
        assert summary["no_impairment_count"] == 0
        assert summary["total_impairment_loss"] == "600.00"
        assert summary["avg_impairment"] == "300.00"
