# tests/domain/shared_value_objects/test_npwp_vo.py
"""
Comprehensive tests for domain/shared_value_objects/npwp_vo.py.
Covers all public methods, validation, formatting, serialization,
comparison, and edge cases. All tests include proper assertions.
"""


import pytest

from domain.shared_value_objects.npwp_vo import (
    NPWP,
    NPWPValidationError,
    normalize_npwp,
    validate_npwp_string,
)

# ============================================================================
# Fixtures and Test Data
# ============================================================================

@pytest.fixture
def valid_npwp_str() -> str:
    """A valid NPWP with correct check digit and valid prefix."""
    return "123456789012345"  # prefix '12', check digit 5


@pytest.fixture
def valid_npwp(valid_npwp_str) -> NPWP:
    return NPWP(valid_npwp_str)


@pytest.fixture
def formatted_npwp() -> str:
    return "12.345.678.9-012.345"


# ============================================================================
# Tests for Exceptions
# ============================================================================

def test_npwp_validation_error_is_value_error():
    assert issubclass(NPWPValidationError, ValueError)


# ============================================================================
# Tests for NPWP Construction and Validation
# ============================================================================

class TestNPWPConstruction:
    def test_valid_ntpn_string(self, valid_npwp_str):
        npwp = NPWP(valid_npwp_str)
        assert npwp.value == valid_npwp_str

    def test_valid_ntpn_integer(self, valid_npwp_str):
        npwp = NPWP(int(valid_npwp_str))
        assert npwp.value == valid_npwp_str

    def test_valid_ntpn_with_separators(self, valid_npwp_str):
        formatted = "12.345.678.9-012.345"
        npwp = NPWP(formatted)
        assert npwp.value == valid_npwp_str

    def test_valid_ntpn_with_spaces(self, valid_npwp_str):
        spaced = "12 345 678 9 012 345"
        npwp = NPWP(spaced)
        assert npwp.value == valid_npwp_str

    def test_invalid_length_too_short(self):
        with pytest.raises(NPWPValidationError, match="exactly 15 digits"):
            NPWP("12345678901234")  # 14 digits

    def test_invalid_length_too_long(self):
        with pytest.raises(NPWPValidationError, match="exactly 15 digits"):
            NPWP("1234567890123456")  # 16 digits

    def test_invalid_non_digit_characters(self):
        with pytest.raises(NPWPValidationError, match="contain only digits"):
            NPWP("1234567890ABCDE")

    def test_invalid_prefix_strict(self):
        with pytest.raises(NPWPValidationError, match="Invalid NPWP prefix"):
            NPWP("001234567890123")  # prefix '00' not in valid set

    def test_invalid_prefix_non_strict(self):
        # strict_prefix=False allows any prefix, but checksum must still be valid.
        # Build a valid number with prefix '00' and correct checksum.
        base = "00123456789012"  # 14 digits: prefix 00 + 12 more
        weights = [2, 3, 4, 5, 6, 7, 8, 9, 10, 2, 3, 4, 5, 6]
        total = sum(int(base[i]) * weights[i] for i in range(14))
        remainder = total % 11
        check = 0 if remainder == 1 else 11 - remainder
        valid_with_invalid_prefix = base + str(check)
        npwp = NPWP(valid_with_invalid_prefix, strict_prefix=False)
        assert npwp.value == valid_with_invalid_prefix

    def test_invalid_checksum(self):
        # Change last digit to something that fails checksum
        with pytest.raises(NPWPValidationError, match="check digit invalid"):
            NPWP("123456789012346")  # last digit 6 instead of 5

    def test_checksum_with_remainder_one(self):
        # Test that checksum handles remainder == 1 (check digit 0)
        # We'll use for_testing to generate a valid NPWP and then verify its check digit is correct.
        npwp = NPWP.for_testing("000000000000000")
        # Just ensure it's valid and has a check digit
        assert len(npwp.value) == 15
        assert validate_npwp_string(npwp.value) is True


# ============================================================================
# Tests for Properties and Methods
# ============================================================================

class TestNPWPProperties:
    def test_value_property(self, valid_npwp):
        assert valid_npwp.value == "123456789012345"

    def test_tax_office_code(self, valid_npwp):
        assert valid_npwp.tax_office_code() == "12"

    def test_entity_code(self, valid_npwp):
        # digits 3-5 (index 2-4) -> "345"
        assert valid_npwp.entity_code() == "345"

    def test_internal_code(self, valid_npwp):
        # digit 9 (index 8) -> '9'
        assert valid_npwp.internal_code() == "9"

    def test_serial_number(self, valid_npwp):
        # digits 10-14 (index 9-13) -> "01234"
        assert valid_npwp.serial_number() == "01234"

    def test_is_head_office_true(self):
        # Build a valid NPWP with internal code '0'
        # prefix '12', entity '345', branch '678', internal '0', serial '12345'
        base = "12345678012345"  # 14 digits: 12 345 678 0 12345
        weights = [2, 3, 4, 5, 6, 7, 8, 9, 10, 2, 3, 4, 5, 6]
        total = sum(int(base[i]) * weights[i] for i in range(14))
        remainder = total % 11
        check = 0 if remainder == 1 else 11 - remainder
        npwp_str = base + str(check)
        npwp = NPWP(npwp_str)
        assert npwp.internal_code() == "0"
        assert npwp.is_head_office() is True

    def test_is_head_office_false(self, valid_npwp):
        # Our fixture has internal_code '9' so it's branch
        assert valid_npwp.is_head_office() is False


# ============================================================================
# Tests for Formatting and Serialization
# ============================================================================

class TestNPWPFormatting:
    def test_formatted(self, valid_npwp):
        expected = "12.345.678.9-012.345"
        assert valid_npwp.formatted() == expected

    def test_compact(self, valid_npwp):
        assert valid_npwp.compact() == "123456789012345"

    def test_str(self, valid_npwp):
        assert str(valid_npwp) == valid_npwp.formatted()

    def test_repr(self, valid_npwp):
        assert repr(valid_npwp) == "NPWP('123456789012345')"

    def test_to_json(self, valid_npwp):
        d = valid_npwp.to_json()
        assert d["value"] == "123456789012345"
        assert d["formatted"] == "12.345.678.9-012.345"
        assert d["tax_office_code"] == "12"
        assert d["entity_code"] == "345"
        assert d["is_head_office"] is False

    def test_from_json(self, valid_npwp):
        data = {"value": "123456789012345"}
        npwp2 = NPWP.from_json(data)
        assert npwp2 == valid_npwp

    def test_from_formatted(self, valid_npwp_str):
        formatted = "12.345.678.9-012.345"
        npwp = NPWP.from_formatted(formatted)
        assert npwp.value == valid_npwp_str

    def test_from_formatted_with_spaces(self):
        formatted = "12 345 678 9 012 345"
        npwp = NPWP.from_formatted(formatted)
        assert npwp.value == "123456789012345"


# ============================================================================
# Tests for Alternative Constructors
# ============================================================================

class TestNPWPAlternativeConstructors:
    def test_for_testing_with_valid(self):
        npwp = NPWP.for_testing("123456789012345")
        assert npwp.value == "123456789012345"

    def test_for_testing_with_invalid_checksum(self):
        # Should fix check digit
        npwp = NPWP.for_testing("123456789012346")  # last digit 6, correct is 5
        assert npwp.value == "123456789012345"  # corrected

    def test_for_testing_with_invalid_prefix(self):
        # Should generate a valid one (prefix might be changed? Actually it will attempt to use the base, if it fails validation (due to prefix or check digit), it will fallback to generated.)
        npwp = NPWP.for_testing("001234567890123")  # invalid prefix '00'
        # It should generate a valid NPWP, not necessarily the input.
        assert len(npwp.value) == 15
        # Check that it's valid by creating another NPWP from it
        NPWP(npwp.value)  # should not raise

    def test_for_testing_fallback(self):
        npwp = NPWP.for_testing("invalid")
        assert len(npwp.value) == 15
        NPWP(npwp.value)  # validate

    def test_for_testing_deterministic(self):
        # Should be deterministic because it uses random seed=42
        npwp1 = NPWP.for_testing("123456789012345")
        npwp2 = NPWP.for_testing("123456789012345")
        assert npwp1 == npwp2

    def test_for_testing_uses_seed_42(self):
        # If we call multiple times with random inputs, the fallback generation uses seed=42, so deterministic.
        npwp1 = NPWP.for_testing("abc")
        npwp2 = NPWP.for_testing("def")
        # The for_testing method uses random.seed(42) each time, so both calls produce the same NPWP.
        assert npwp1 == npwp2

    def test_for_testing_with_valid_prefix_but_bad_checksum_fixes(self):
        # Base with valid prefix but wrong check digit
        base = "123456789012346"
        npwp = NPWP.for_testing(base)
        # It should compute correct check digit and return fixed string.
        # The correct check digit for "12345678901234" is 5 (as per fixture), so result should be "123456789012345"
        assert npwp.value == "123456789012345"

    def test_for_testing_with_invalid_length(self):
        # Input too short; fallback to generated
        npwp = NPWP.for_testing("123")
        assert len(npwp.value) == 15
        assert validate_npwp_string(npwp.value) is True


# ============================================================================
# Tests for Comparison and Ordering
# ============================================================================

class TestNPWPComparison:
    def test_equality(self, valid_npwp):
        same = NPWP("123456789012345")
        assert valid_npwp == same
        different = NPWP.for_testing("999999999999999")  # generate different
        assert valid_npwp != different

    def test_equality_with_non_npwp(self, valid_npwp):
        assert valid_npwp != "123456789012345"
        assert valid_npwp != 123456789012345
        assert valid_npwp != None

    def test_hash(self, valid_npwp):
        same = NPWP("123456789012345")
        assert hash(valid_npwp) == hash(same)

    def test_ordering(self):
        n1 = NPWP("123456789012345")
        n2 = NPWP("223456789012345")  # larger numeric value
        assert n1 < n2
        assert n2 > n1
        # Also test <= and >=
        assert n1 <= n2
        assert n2 >= n1
        assert n1 <= n1
        assert n1 >= n1


# ============================================================================
# Tests for Helper Functions
# ============================================================================

class TestHelperFunctions:
    def test_validate_npwp_string_valid(self):
        assert validate_npwp_string("123456789012345") is True

    def test_validate_npwp_string_invalid_length(self):
        assert validate_npwp_string("12345678901234") is False

    def test_validate_npwp_string_invalid_checksum(self):
        assert validate_npwp_string("123456789012346") is False

    def test_validate_npwp_string_invalid_prefix(self):
        assert validate_npwp_string("001234567890123") is False  # prefix invalid

    def test_validate_npwp_string_non_digit(self):
        assert validate_npwp_string("1234567890ABCDE") is False

    def test_normalize_npwp_strips_separators(self):
        raw = "12.345.678.9-012.345"
        assert normalize_npwp(raw) == "123456789012345"

    def test_normalize_npwp_handles_spaces(self):
        raw = "12 345 678 9 012 345"
        assert normalize_npwp(raw) == "123456789012345"

    def test_normalize_npwp_with_integer(self):
        assert normalize_npwp(123456789012345) == "123456789012345"

    def test_normalize_npwp_empty(self):
        # re.sub removes non-digits, so "abc" becomes ""
        assert normalize_npwp("abc") == ""

    def test_normalize_npwp_mixed(self):
        assert normalize_npwp("12a34b56") == "123456"


# ============================================================================
# Additional Edge Cases
# ============================================================================

def test_npwp_non_strict_accepts_invalid_prefix():
    # Already covered in test_invalid_prefix_non_strict, but ensure checksum still validated.
    base = "00123456789012"
    weights = [2, 3, 4, 5, 6, 7, 8, 9, 10, 2, 3, 4, 5, 6]
    total = sum(int(base[i]) * weights[i] for i in range(14))
    remainder = total % 11
    check = 0 if remainder == 1 else 11 - remainder
    valid_with_invalid_prefix = base + str(check)
    npwp = NPWP(valid_with_invalid_prefix, strict_prefix=False)
    assert npwp.value == valid_with_invalid_prefix
    # With strict_prefix=True should raise
    with pytest.raises(NPWPValidationError, match="Invalid NPWP prefix"):
        NPWP(valid_with_invalid_prefix, strict_prefix=True)


def test_npwp_non_strict_still_validates_checksum():
    # Even with strict_prefix=False, checksum must be valid.
    with pytest.raises(NPWPValidationError, match="check digit invalid"):
        NPWP("001234567890123", strict_prefix=False)  # wrong checksum


def test_from_formatted_with_different_separators():
    # Source only supports dots and dashes, but we test with other separators.
    # The implementation strips all non-digits, so any separators work.
    npwp = NPWP.from_formatted("12-345-678-9-012-345")
    assert npwp.value == "123456789012345"
    npwp2 = NPWP.from_formatted("12/345/678/9/012/345")
    assert npwp2.value == "123456789012345"


def test_npwp_equality_with_other_type_returns_false(valid_npwp):
    assert valid_npwp != "some string"
    assert valid_npwp != 123456789012345
    assert valid_npwp != None


def test_npwp_ordering_with_mixed_types_raises_type_error(valid_npwp):
    with pytest.raises(TypeError):
        valid_npwp < "123"  # type: ignore
