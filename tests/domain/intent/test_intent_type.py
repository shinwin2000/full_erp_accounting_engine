# test_intent_type.py
# ====================
# Comprehensive tests for domain/intent/intent_type.py.
# Covers all enum members and the from_string method.

import pytest

from domain.intent.intent_type import IntentType


class TestIntentType:
    """Tests for the IntentType enum."""

    def test_members_exist(self):
        """All expected enum members are defined."""
        assert hasattr(IntentType, "CREATE_JOURNAL")
        assert hasattr(IntentType, "CREATE_INVOICE")
        assert hasattr(IntentType, "CREATE_PAYMENT")
        assert hasattr(IntentType, "CREATE_PURCHASE_ORDER")
        assert hasattr(IntentType, "CREATE_SALES_ORDER")
        assert hasattr(IntentType, "RECORD_CASH_RECEIPT")
        assert hasattr(IntentType, "RECORD_CASH_DISBURSEMENT")
        assert hasattr(IntentType, "ADJUST_INVENTORY")
        assert hasattr(IntentType, "DISPOSE_ASSET")
        assert hasattr(IntentType, "CLOSE_PERIOD")
        assert hasattr(IntentType, "APPROVE_TRANSACTION")
        assert hasattr(IntentType, "REJECT_TRANSACTION")

    def test_member_is_instance(self):
        """Enum members are instances of the enum class."""
        assert isinstance(IntentType.CREATE_JOURNAL, IntentType)

    def test_from_string_valid_uppercase(self):
        """from_string should return correct enum for uppercase strings."""
        assert IntentType.from_string("CREATE_JOURNAL") == IntentType.CREATE_JOURNAL
        assert IntentType.from_string("CREATE_INVOICE") == IntentType.CREATE_INVOICE
        assert IntentType.from_string("CREATE_PAYMENT") == IntentType.CREATE_PAYMENT
        assert IntentType.from_string("CREATE_PURCHASE_ORDER") == IntentType.CREATE_PURCHASE_ORDER
        assert IntentType.from_string("CREATE_SALES_ORDER") == IntentType.CREATE_SALES_ORDER
        assert IntentType.from_string("RECORD_CASH_RECEIPT") == IntentType.RECORD_CASH_RECEIPT
        assert IntentType.from_string("RECORD_CASH_DISBURSEMENT") == IntentType.RECORD_CASH_DISBURSEMENT
        assert IntentType.from_string("ADJUST_INVENTORY") == IntentType.ADJUST_INVENTORY
        assert IntentType.from_string("DISPOSE_ASSET") == IntentType.DISPOSE_ASSET
        assert IntentType.from_string("CLOSE_PERIOD") == IntentType.CLOSE_PERIOD
        assert IntentType.from_string("APPROVE_TRANSACTION") == IntentType.APPROVE_TRANSACTION
        assert IntentType.from_string("REJECT_TRANSACTION") == IntentType.REJECT_TRANSACTION

    def test_from_string_valid_lowercase(self):
        """from_string should handle lowercase input (converts to uppercase internally)."""
        assert IntentType.from_string("create_journal") == IntentType.CREATE_JOURNAL
        assert IntentType.from_string("create_invoice") == IntentType.CREATE_INVOICE
        assert IntentType.from_string("adjust_inventory") == IntentType.ADJUST_INVENTORY
        assert IntentType.from_string("approve_transaction") == IntentType.APPROVE_TRANSACTION

    def test_from_string_valid_mixed_case(self):
        """from_string should handle mixed case input."""
        assert IntentType.from_string("CrEaTe_JouRnal") == IntentType.CREATE_JOURNAL
        assert IntentType.from_string("ReCorD_CasH_ReCeIpT") == IntentType.RECORD_CASH_RECEIPT

    def test_from_string_raises_for_unknown(self):
        """from_string should raise ValueError for unknown intent type strings."""
        with pytest.raises(ValueError, match="Unknown IntentType: UNKNOWN"):
            IntentType.from_string("UNKNOWN")

        with pytest.raises(ValueError, match="Unknown IntentType: invalid"):
            IntentType.from_string("invalid")

        with pytest.raises(ValueError, match="Unknown IntentType: "):
            IntentType.from_string("")

    def test_from_string_raises_for_nonexistent_enum(self):
        """from_string should raise ValueError for strings that don't match any enum member."""
        with pytest.raises(ValueError, match="Unknown IntentType: NON_EXISTENT"):
            IntentType.from_string("NON_EXISTENT")

    def test_all_members_can_be_converted_back(self):
        """Test round-trip: from_string(member.name) should return the member."""
        for member in IntentType:
            assert IntentType.from_string(member.name) == member

    def test_enum_values_are_auto_assigned(self):
        """Ensure that auto() assigns unique integer values."""
        values = [member.value for member in IntentType]
        assert len(values) == len(set(values))  # all unique
        # Values start from 1 and increment by 1 (auto() behavior)
        # We can check that the first is 1 and the last is the count.
        assert IntentType.CREATE_JOURNAL.value == 1
        assert IntentType.REJECT_TRANSACTION.value == len(IntentType)