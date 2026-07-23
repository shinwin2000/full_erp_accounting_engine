# test_quantity_vo.py
# Comprehensive tests for domain/shared_value_objects/quantity_vo.py
# Covers all classes, methods, edge cases, exceptions, and domain logic.

import pytest
from decimal import Decimal, ROUND_HALF_EVEN
from domain.shared_value_objects.quantity_vo import (
    InvalidQuantityError,
    QuantityError,
    QuantityVO,
    UnitConversionError,
    UnitMismatchError,
    UnitOfMeasure,
    average_quantity,
    normalize_quantities,
    sum_quantities,
)


# -------------------- Fixtures --------------------
@pytest.fixture
def q_pcs():
    return QuantityVO(Decimal("10"), UnitOfMeasure.PCS)


@pytest.fixture
def q_dozen():
    return QuantityVO(Decimal("2"), UnitOfMeasure.DOZEN)


@pytest.fixture
def q_kg():
    return QuantityVO(Decimal("5"), UnitOfMeasure.KG)


@pytest.fixture
def q_gram():
    return QuantityVO(Decimal("500"), UnitOfMeasure.GRAM)


@pytest.fixture
def q_liter():
    return QuantityVO(Decimal("3"), UnitOfMeasure.LITER)


@pytest.fixture
def q_ml():
    return QuantityVO(Decimal("1500"), UnitOfMeasure.ML)


@pytest.fixture
def q_meter():
    return QuantityVO(Decimal("10"), UnitOfMeasure.METER)


@pytest.fixture
def q_cm():
    return QuantityVO(Decimal("100"), UnitOfMeasure.CM)


# -------------------- Tests for UnitOfMeasure Enum --------------------
class TestUnitOfMeasure:
    def test_from_string_valid(self):
        assert UnitOfMeasure.from_string("pcs") == UnitOfMeasure.PCS
        assert UnitOfMeasure.from_string("KG") == UnitOfMeasure.KG
        assert UnitOfMeasure.from_string("Liter") == UnitOfMeasure.LITER
        assert UnitOfMeasure.from_string("GAL") == UnitOfMeasure.GAL
        assert UnitOfMeasure.from_string("sq_ft") == UnitOfMeasure.SQ_FT

    def test_from_string_invalid(self):
        assert UnitOfMeasure.from_string("invalid") is None
        assert UnitOfMeasure.from_string("") is None

    def test_is_countable(self):
        countables = [
            UnitOfMeasure.PCS, UnitOfMeasure.PAIR, UnitOfMeasure.DOZEN,
            UnitOfMeasure.GROSS, UnitOfMeasure.SET, UnitOfMeasure.BOX,
            UnitOfMeasure.CARTON, UnitOfMeasure.PALLET
        ]
        non_countables = [
            UnitOfMeasure.KG, UnitOfMeasure.GRAM, UnitOfMeasure.LITER,
            UnitOfMeasure.METER, UnitOfMeasure.HOUR, UnitOfMeasure.SQ_M
        ]
        for u in countables:
            assert u.is_countable() is True
        for u in non_countables:
            assert u.is_countable() is False

    def test_is_weight(self):
        weights = [UnitOfMeasure.KG, UnitOfMeasure.GRAM, UnitOfMeasure.MG,
                   UnitOfMeasure.TON, UnitOfMeasure.LB, UnitOfMeasure.OZ]
        non_weights = [UnitOfMeasure.PCS, UnitOfMeasure.LITER, UnitOfMeasure.METER]
        for u in weights:
            assert u.is_weight() is True
        for u in non_weights:
            assert u.is_weight() is False

    def test_is_volume(self):
        volumes = [UnitOfMeasure.LITER, UnitOfMeasure.ML, UnitOfMeasure.GAL, UnitOfMeasure.QUART]
        non_volumes = [UnitOfMeasure.PCS, UnitOfMeasure.KG, UnitOfMeasure.METER]
        for u in volumes:
            assert u.is_volume() is True
        for u in non_volumes:
            assert u.is_volume() is False

    def test_is_length(self):
        lengths = [UnitOfMeasure.METER, UnitOfMeasure.CM, UnitOfMeasure.MM,
                   UnitOfMeasure.KM, UnitOfMeasure.INCH, UnitOfMeasure.FT, UnitOfMeasure.YD]
        non_lengths = [UnitOfMeasure.PCS, UnitOfMeasure.KG, UnitOfMeasure.LITER]
        for u in lengths:
            assert u.is_length() is True
        for u in non_lengths:
            assert u.is_length() is False


# -------------------- Tests for QuantityVO --------------------
class TestQuantityVO:
    def test_construction_valid(self):
        q = QuantityVO(Decimal("10.5"), UnitOfMeasure.PCS)
        assert q.value == Decimal("10.500")  # normalized to 3 decimal places
        assert q.unit == UnitOfMeasure.PCS

    def test_construction_zero(self):
        q = QuantityVO(Decimal("0"), UnitOfMeasure.KG)
        assert q.value == Decimal("0")
        assert q.is_zero is True

    def test_construction_negative_raises(self):
        with pytest.raises(InvalidQuantityError, match="cannot be negative"):
            QuantityVO(Decimal("-1"), UnitOfMeasure.PCS)

    def test_construction_non_decimal_raises(self):
        with pytest.raises(InvalidQuantityError, match="Value must be Decimal"):
            QuantityVO(10, UnitOfMeasure.PCS)  # int not allowed

    def test_of_with_decimal(self):
        q = QuantityVO.of(Decimal("5.5"), UnitOfMeasure.KG)
        assert q.value == Decimal("5.500")
        assert q.unit == UnitOfMeasure.KG

    def test_of_with_int(self):
        q = QuantityVO.of(5, UnitOfMeasure.PCS)
        assert q.value == Decimal("5")
        assert q.unit == UnitOfMeasure.PCS

    def test_of_with_str(self):
        q = QuantityVO.of("3.14", UnitOfMeasure.LITER)
        assert q.value == Decimal("3.140")
        assert q.unit == UnitOfMeasure.LITER

    def test_of_with_float(self):
        q = QuantityVO.of(2.5, UnitOfMeasure.KG)
        assert q.value == Decimal("2.500")
        assert q.unit == UnitOfMeasure.KG

    def test_of_with_unsupported_type_raises(self):
        with pytest.raises(InvalidQuantityError, match="Unsupported value type"):
            QuantityVO.of([1, 2], UnitOfMeasure.PCS)  # list not supported

    def test_of_with_string_unit(self):
        q = QuantityVO.of(10, "kg")
        assert q.unit == UnitOfMeasure.KG
        q2 = QuantityVO.of(5, "PCS")
        assert q2.unit == UnitOfMeasure.PCS
        with pytest.raises(QuantityError, match="Unknown unit"):
            QuantityVO.of(10, "invalid")

    def test_zero(self):
        q = QuantityVO.zero(UnitOfMeasure.KG)
        assert q.value == Decimal("0")
        assert q.unit == UnitOfMeasure.KG
        assert q.is_zero is True

    def test_from_dict_valid(self):
        data = {"value": "10.5", "unit": "pcs"}
        q = QuantityVO.from_dict(data)
        assert q.value == Decimal("10.500")
        assert q.unit == UnitOfMeasure.PCS

    def test_from_dict_invalid_unit(self):
        data = {"value": "10", "unit": "invalid"}
        with pytest.raises(QuantityError, match="Invalid unit in dict"):
            QuantityVO.from_dict(data)

    def test_convert_to_same_unit(self, q_pcs):
        converted = q_pcs.convert_to(UnitOfMeasure.PCS)
        assert converted == q_pcs

    def test_convert_to_kg_to_gram(self, q_kg):
        converted = q_kg.convert_to(UnitOfMeasure.GRAM)
        assert converted.value == Decimal("5000")
        assert converted.unit == UnitOfMeasure.GRAM

    def test_convert_to_gram_to_kg(self, q_gram):
        converted = q_gram.convert_to(UnitOfMeasure.KG)
        assert converted.value == Decimal("0.500")
        assert converted.unit == UnitOfMeasure.KG

    def test_convert_to_dozen_to_pcs(self, q_dozen):
        converted = q_dozen.convert_to(UnitOfMeasure.PCS)
        assert converted.value == Decimal("24")
        assert converted.unit == UnitOfMeasure.PCS

    def test_convert_to_pcs_to_dozen(self, q_pcs):
        # 10 pcs = 10/12 = 0.833 dozen, rounded to 3 decimals
        converted = q_pcs.convert_to(UnitOfMeasure.DOZEN)
        expected = Decimal("10") / Decimal("12")
        # quantity will be normalized to 3 decimal places
        quantize = Decimal("0.001")
        expected = expected.quantize(quantize, rounding=ROUND_HALF_EVEN)
        assert converted.value == expected
        assert converted.unit == UnitOfMeasure.DOZEN

    def test_convert_to_liter_to_ml(self, q_liter):
        converted = q_liter.convert_to(UnitOfMeasure.ML)
        assert converted.value == Decimal("3000")
        assert converted.unit == UnitOfMeasure.ML

    def test_convert_to_ml_to_liter(self, q_ml):
        converted = q_ml.convert_to(UnitOfMeasure.LITER)
        assert converted.value == Decimal("1.500")
        assert converted.unit == UnitOfMeasure.LITER

    def test_convert_to_incompatible_raises(self, q_pcs):
        with pytest.raises(UnitConversionError, match="Cannot convert pcs to kg"):
            q_pcs.convert_to(UnitOfMeasure.KG)

    def test_is_convertible_to(self, q_kg):
        assert q_kg.is_convertible_to(UnitOfMeasure.GRAM) is True
        assert q_kg.is_convertible_to(UnitOfMeasure.PCS) is False
        assert q_kg.is_convertible_to(UnitOfMeasure.KG) is True

    def test_get_conversion_map_keys(self):
        keys = QuantityVO._get_conversion_map_keys()
        assert (UnitOfMeasure.KG, UnitOfMeasure.GRAM) in keys
        assert (UnitOfMeasure.LITER, UnitOfMeasure.ML) in keys
        assert (UnitOfMeasure.METER, UnitOfMeasure.CM) in keys
        assert (UnitOfMeasure.DOZEN, UnitOfMeasure.PCS) in keys
        assert (UnitOfMeasure.SQ_M, UnitOfMeasure.SQ_FT) in keys
        # not all pairs are present
        assert (UnitOfMeasure.PCS, UnitOfMeasure.KG) not in keys

    # ---- Properties ----
    def test_is_zero(self, q_pcs):
        assert q_pcs.is_zero is False
        zero = QuantityVO(Decimal("0"), UnitOfMeasure.PCS)
        assert zero.is_zero is True

    def test_is_positive(self, q_pcs):
        assert q_pcs.is_positive is True
        zero = QuantityVO(Decimal("0"), UnitOfMeasure.PCS)
        assert zero.is_positive is False

    def test_as_integer(self, q_pcs):
        assert q_pcs.as_integer == 10
        q_decimal = QuantityVO(Decimal("10.5"), UnitOfMeasure.PCS)
        assert q_decimal.as_integer is None
        q_zero = QuantityVO(Decimal("0"), UnitOfMeasure.PCS)
        assert q_zero.as_integer == 0

    # ---- Arithmetic ----
    def test_add_same_unit(self, q_pcs):
        q2 = QuantityVO(Decimal("5"), UnitOfMeasure.PCS)
        result = q_pcs.add(q2)
        assert result.value == Decimal("15")
        assert result.unit == UnitOfMeasure.PCS

    def test_add_different_units_convertible(self, q_pcs, q_dozen):
        # 10 pcs + 2 dozen = 10 + 24 = 34 pcs
        result = q_pcs.add(q_dozen)
        assert result.value == Decimal("34")
        assert result.unit == UnitOfMeasure.PCS

    def test_add_different_units_incompatible_raises(self, q_pcs, q_kg):
        with pytest.raises(UnitMismatchError, match="Cannot add pcs and kg"):
            q_pcs.add(q_kg)

    def test_subtract_same_unit(self, q_pcs):
        q2 = QuantityVO(Decimal("3"), UnitOfMeasure.PCS)
        result = q_pcs.subtract(q2)
        assert result.value == Decimal("7")
        assert result.unit == UnitOfMeasure.PCS

    def test_subtract_different_units_convertible(self, q_pcs, q_dozen):
        # 10 pcs - 2 dozen (24 pcs) would be negative, so raise
        # Actually 10 - 24 = -14, so should raise InvalidQuantityError
        with pytest.raises(InvalidQuantityError, match="Result would be negative"):
            q_pcs.subtract(q_dozen)
        # Use larger pcs: 30 pcs - 1 dozen (12 pcs) = 18 pcs
        q30 = QuantityVO(Decimal("30"), UnitOfMeasure.PCS)
        result = q30.subtract(q_dozen)
        assert result.value == Decimal("18")
        assert result.unit == UnitOfMeasure.PCS

    def test_subtract_different_units_incompatible_raises(self, q_pcs, q_kg):
        with pytest.raises(UnitMismatchError, match="Cannot subtract kg from pcs"):
            q_pcs.subtract(q_kg)

    def test_multiply(self, q_pcs):
        result = q_pcs.multiply(Decimal("2.5"))
        assert result.value == Decimal("25")
        assert result.unit == UnitOfMeasure.PCS
        # with int
        result2 = q_pcs.multiply(3)
        assert result2.value == Decimal("30")
        # with float
        result3 = q_pcs.multiply(1.5)
        assert result3.value == Decimal("15.000")

    def test_multiply_unsupported_factor_raises(self, q_pcs):
        with pytest.raises(InvalidQuantityError, match="Factor must be numeric"):
            q_pcs.multiply("string")

    def test_divide(self, q_pcs):
        result = q_pcs.divide(Decimal("2"))
        assert result.value == Decimal("5")
        assert result.unit == UnitOfMeasure.PCS

    def test_divide_by_zero_raises(self, q_pcs):
        with pytest.raises(QuantityError, match="Division by zero"):
            q_pcs.divide(Decimal("0"))

    def test_divide_unsupported_divisor_raises(self, q_pcs):
        with pytest.raises(InvalidQuantityError, match="Divisor must be numeric"):
            q_pcs.divide("2")

    # ---- Dunder operators ----
    def test_operator_add(self, q_pcs):
        q2 = QuantityVO(Decimal("5"), UnitOfMeasure.PCS)
        result = q_pcs + q2
        assert result.value == Decimal("15")

    def test_operator_sub(self, q_pcs):
        q2 = QuantityVO(Decimal("3"), UnitOfMeasure.PCS)
        result = q_pcs - q2
        assert result.value == Decimal("7")

    def test_operator_mul(self, q_pcs):
        result = q_pcs * 2
        assert result.value == Decimal("20")
        result2 = 2 * q_pcs  # __rmul__
        assert result2.value == Decimal("20")

    def test_operator_truediv(self, q_pcs):
        result = q_pcs / 2
        assert result.value == Decimal("5")

    # ---- Comparison ----
    def test_compare_same_unit(self, q_pcs):
        q2 = QuantityVO(Decimal("10"), UnitOfMeasure.PCS)
        assert q_pcs.compare(q2) == 0
        q3 = QuantityVO(Decimal("12"), UnitOfMeasure.PCS)
        assert q_pcs.compare(q3) == -1
        q4 = QuantityVO(Decimal("8"), UnitOfMeasure.PCS)
        assert q_pcs.compare(q4) == 1

    def test_compare_different_units_convertible(self, q_pcs, q_dozen):
        # 10 pcs vs 1 dozen (12 pcs) => 10 < 12 => -1
        q1_dozen = QuantityVO(Decimal("1"), UnitOfMeasure.DOZEN)
        assert q_pcs.compare(q1_dozen) == -1
        # 2 dozen (24 pcs) vs 10 pcs => 1
        assert q_dozen.compare(q_pcs) == 1
        # 10 pcs vs 10/12 dozen (0.833) should be 0? We'll test exact conversion rounding.
        # Use quantities that are exactly convertible: 2 dozen vs 24 pcs.
        q24 = QuantityVO(Decimal("24"), UnitOfMeasure.PCS)
        assert q_dozen.compare(q24) == 0

    def test_compare_incompatible_units_raises(self, q_pcs, q_kg):
        with pytest.raises(UnitMismatchError, match="Cannot compare pcs and kg"):
            q_pcs.compare(q_kg)

    def test_equality_same_unit(self, q_pcs):
        q2 = QuantityVO(Decimal("10"), UnitOfMeasure.PCS)
        assert q_pcs == q2
        q3 = QuantityVO(Decimal("12"), UnitOfMeasure.PCS)
        assert q_pcs != q3

    def test_equality_different_units_convertible(self, q_dozen):
        q24 = QuantityVO(Decimal("24"), UnitOfMeasure.PCS)
        assert q_dozen == q24
        q23 = QuantityVO(Decimal("23"), UnitOfMeasure.PCS)
        assert q_dozen != q23

    def test_equality_different_units_incompatible(self, q_pcs, q_kg):
        # Should return False, not raise
        assert q_pcs != q_kg
        assert not (q_pcs == q_kg)

    def test_ordering(self, q_pcs):
        q2 = QuantityVO(Decimal("12"), UnitOfMeasure.PCS)
        assert q_pcs < q2
        assert q_pcs <= q2
        assert q2 > q_pcs
        assert q2 >= q_pcs
        # equal
        q3 = QuantityVO(Decimal("10"), UnitOfMeasure.PCS)
        assert q_pcs <= q3
        assert q_pcs >= q3

    def test_hash(self, q_pcs):
        q2 = QuantityVO(Decimal("10"), UnitOfMeasure.PCS)
        assert hash(q_pcs) == hash(q2)
        # Different unit but same after conversion? Hash is based on value and unit, so not equal
        q_dozen2 = QuantityVO(Decimal("1"), UnitOfMeasure.DOZEN)
        assert hash(q_pcs) != hash(q_dozen2)  # because unit different even if value equivalent (10 pcs != 1 dozen)

    # ---- Serialization ----
    def test_to_dict(self, q_pcs):
        data = q_pcs.to_dict()
        assert data["value"] == "10.000"
        assert data["unit"] == "pcs"
        assert data["is_zero"] is False
        assert data["is_positive"] is True

    def test_to_db_record(self, q_pcs):
        record = q_pcs.to_db_record()
        assert record["quantity"] == Decimal("10.000")
        assert record["unit"] == "pcs"

    # ---- __str__ and __repr__ ----
    def test_str_with_integer_value(self, q_pcs):
        assert str(q_pcs) == "10 pcs"

    def test_str_with_decimal(self):
        q = QuantityVO(Decimal("10.500"), UnitOfMeasure.KG)
        # normalizes to 10.5, but with precision 3 it becomes 10.500, str strips trailing zeros
        # Actually __str__ normalizes and removes trailing zeros: "10.5 kg"
        # Our implementation uses normalize then format, so should be "10.5 kg"
        # But because we set PRECISION=3, we quantize to 0.001, so 10.500 -> "10.500", then strip trailing zeros -> "10.5"
        assert str(q) == "10.5 kg"
        q2 = QuantityVO(Decimal("10.123"), UnitOfMeasure.PCS)
        assert str(q2) == "10.123 pcs"

    def test_repr(self, q_pcs):
        assert repr(q_pcs) == "QuantityVO('10.000', pcs)"


# -------------------- Tests for Helper Functions --------------------
class TestHelperFunctions:
    def test_sum_quantities_same_unit(self, q_pcs):
        q2 = QuantityVO(Decimal("5"), UnitOfMeasure.PCS)
        result = sum_quantities([q_pcs, q2])
        assert result.value == Decimal("15")
        assert result.unit == UnitOfMeasure.PCS

    def test_sum_quantities_different_units_convertible(self, q_pcs, q_dozen):
        result = sum_quantities([q_pcs, q_dozen], target_unit=UnitOfMeasure.PCS)
        assert result.value == Decimal("34")  # 10 + 24
        assert result.unit == UnitOfMeasure.PCS

    def test_sum_quantities_auto_unit(self, q_pcs, q_dozen):
        # No target_unit: uses unit of first (PCS)
        result = sum_quantities([q_pcs, q_dozen])
        assert result.value == Decimal("34")
        assert result.unit == UnitOfMeasure.PCS

    def test_sum_quantities_different_units_convertible_to_dozen(self, q_pcs, q_dozen):
        result = sum_quantities([q_pcs, q_dozen], target_unit=UnitOfMeasure.DOZEN)
        # 10 pcs = 10/12 = 0.833 dozen, plus 2 dozen = 2.833 dozen
        expected = Decimal("10") / Decimal("12") + Decimal("2")
        quantize = Decimal("0.001")
        expected = expected.quantize(quantize, rounding=ROUND_HALF_EVEN)
        assert result.value == expected
        assert result.unit == UnitOfMeasure.DOZEN

    def test_sum_quantities_incompatible_raises(self, q_pcs, q_kg):
        with pytest.raises(UnitMismatchError, match="Cannot convert kg to pcs"):
            sum_quantities([q_pcs, q_kg], target_unit=UnitOfMeasure.PCS)

    def test_sum_empty_list_raises(self):
        with pytest.raises(QuantityError, match="Cannot sum empty list"):
            sum_quantities([])

    def test_average_quantity(self, q_pcs):
        q2 = QuantityVO(Decimal("20"), UnitOfMeasure.PCS)
        q3 = QuantityVO(Decimal("30"), UnitOfMeasure.PCS)
        result = average_quantity([q_pcs, q2, q3])
        assert result.value == Decimal("20")
        assert result.unit == UnitOfMeasure.PCS

    def test_average_quantity_different_units(self, q_pcs, q_dozen):
        # 10 pcs, 2 dozen (24 pcs), average = (10+24)/2 = 17 pcs
        result = average_quantity([q_pcs, q_dozen])
        assert result.value == Decimal("17")
        assert result.unit == UnitOfMeasure.PCS

    def test_average_empty_list_raises(self):
        with pytest.raises(QuantityError, match="Cannot average empty list"):
            average_quantity([])

    def test_normalize_quantities(self, q_pcs, q_dozen):
        result = normalize_quantities([q_pcs, q_dozen], UnitOfMeasure.PCS)
        assert len(result) == 2
        assert result[0].value == Decimal("10.000")
        assert result[0].unit == UnitOfMeasure.PCS
        assert result[1].value == Decimal("24.000")
        assert result[1].unit == UnitOfMeasure.PCS

    def test_normalize_quantities_incompatible_raises(self, q_pcs, q_kg):
        with pytest.raises(UnitMismatchError, match="Cannot convert kg to pcs"):
            normalize_quantities([q_pcs, q_kg], UnitOfMeasure.PCS)

    def test_normalize_quantities_already_same(self, q_pcs):
        q2 = QuantityVO(Decimal("5"), UnitOfMeasure.PCS)
        result = normalize_quantities([q_pcs, q2], UnitOfMeasure.PCS)
        assert result[0] is q_pcs  # should return same object because no conversion needed? Actually convert_to returns self if same unit, so yes.
        assert result[1] is q2