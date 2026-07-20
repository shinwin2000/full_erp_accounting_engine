# test_journal_line_vo.py
# =========================================
# Lengkap: Semua test asli dipertahankan + tambahan test coverage untuk semua metode yang hilang.

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domain.journal.journal_line_vo import JournalLineRepository, JournalLineVO, JournalSide


class TestJournalSide:
    """Tests for the JournalSide enum."""
    def test_members_exist(self):
        assert hasattr(JournalSide, 'DEBIT')
        assert hasattr(JournalSide, 'CREDIT')

    def test_member_is_instance(self):
        assert isinstance(JournalSide.DEBIT, JournalSide)

    # --- TAMBAHAN: Metode yang hilang ---
    def test_opposite(self):
        assert JournalSide.DEBIT.opposite() == JournalSide.CREDIT
        assert JournalSide.CREDIT.opposite() == JournalSide.DEBIT

    def test_is_debit(self):
        assert JournalSide.DEBIT.is_debit() is True
        assert JournalSide.CREDIT.is_debit() is False

    def test_is_credit(self):
        assert JournalSide.CREDIT.is_credit() is True
        assert JournalSide.DEBIT.is_credit() is False

    def test_from_string_valid(self):
        assert JournalSide.from_string("debit") == JournalSide.DEBIT
        assert JournalSide.from_string("dr") == JournalSide.DEBIT
        assert JournalSide.from_string("d") == JournalSide.DEBIT
        assert JournalSide.from_string("credit") == JournalSide.CREDIT
        assert JournalSide.from_string("cr") == JournalSide.CREDIT
        assert JournalSide.from_string("c") == JournalSide.CREDIT
        # Case insensitive
        assert JournalSide.from_string("DEBIT") == JournalSide.DEBIT
        assert JournalSide.from_string("CREDIT") == JournalSide.CREDIT

    def test_from_string_invalid(self):
        with pytest.raises(ValueError, match="Invalid journal side"):
            JournalSide.from_string("invalid")


class TestJournalLineVO:
    """Tests for JournalLineVO."""

    def _build_kwargs(self):
        return dict(
            line_id=uuid4(),
            journal_id=uuid4(),
            account_id=uuid4(),
            account_code="ACC-001",
            account_name="Cash",
            side=JournalSide.DEBIT,
            amount=Decimal("100.00"),
            description="Test entry",
            legal_entity_id=uuid4(),
            cost_center="CC-01",
            department="DEPT-A",
            project_id=uuid4(),
            customer_id=uuid4(),
            supplier_id=uuid4(),
            employee_id=uuid4(),
            currency="IDR",
            tax_rate=Decimal("11"),
            tax_amount=Decimal("11.00"),
        )

    def test_construction_success(self):
        kwargs = self._build_kwargs()
        instance = JournalLineVO(**kwargs)
        assert isinstance(instance, JournalLineVO)
        assert instance.line_id == kwargs['line_id']

    # --- Validasi ---
    def test_validation_amount_zero(self):
        kwargs = self._build_kwargs()
        kwargs["amount"] = Decimal("0")
        with pytest.raises(ValueError, match="Amount must be positive"):
            JournalLineVO(**kwargs)

    def test_validation_amount_negative(self):
        kwargs = self._build_kwargs()
        kwargs["amount"] = Decimal("-1")
        with pytest.raises(ValueError, match="Amount must be positive"):
            JournalLineVO(**kwargs)

    def test_validation_account_code_empty(self):
        kwargs = self._build_kwargs()
        kwargs["account_code"] = ""
        with pytest.raises(ValueError, match="Account code cannot be empty"):
            JournalLineVO(**kwargs)

    def test_validation_description_empty(self):
        kwargs = self._build_kwargs()
        kwargs["description"] = ""
        with pytest.raises(ValueError, match="Description cannot be empty"):
            JournalLineVO(**kwargs)

    def test_validation_description_too_short(self):
        kwargs = self._build_kwargs()
        kwargs["description"] = "x"
        with pytest.raises(ValueError, match="Description too short"):
            JournalLineVO(**kwargs)

    def test_validation_tax_rate_out_of_range(self):
        kwargs = self._build_kwargs()
        kwargs["tax_rate"] = Decimal("101")
        with pytest.raises(ValueError, match="Tax rate must be between 0 and 100"):
            JournalLineVO(**kwargs)

        kwargs["tax_rate"] = Decimal("-1")
        with pytest.raises(ValueError, match="Tax rate must be between 0 and 100"):
            JournalLineVO(**kwargs)

    def test_validation_tax_amount_negative(self):
        kwargs = self._build_kwargs()
        kwargs["tax_amount"] = Decimal("-1")
        with pytest.raises(ValueError, match="Tax amount cannot be negative"):
            JournalLineVO(**kwargs)

    # --- Metode yang dilaporkan ---
    def test_is_debit(self):
        instance = self._build_kwargs()
        line = JournalLineVO(**instance)
        assert line.is_debit() is True
        # Change side
        line2 = JournalLineVO(**{**instance, "side": JournalSide.CREDIT})
        assert line2.is_debit() is False

    def test_is_credit(self):
        instance = self._build_kwargs()
        line = JournalLineVO(**instance)
        assert line.is_credit() is False
        line2 = JournalLineVO(**{**instance, "side": JournalSide.CREDIT})
        assert line2.is_credit() is True

    def test_net_amount(self):
        instance = self._build_kwargs()
        line = JournalLineVO(**instance)
        assert line.net_amount() == Decimal("100.00")

    def test_total_with_tax(self):
        instance = self._build_kwargs()
        line = JournalLineVO(**instance)
        assert line.total_with_tax() == Decimal("111.00")

    def test_normalize(self):
        instance = self._build_kwargs()
        line = JournalLineVO(**instance)
        # Modify some fields to ensure normalization
        normalized = line.normalize()
        assert normalized.account_code == "ACC-001"  # already uppercase, but strip
        assert normalized.amount == Decimal("100.00")
        assert normalized.currency == "IDR"
        # Test with spaces
        raw = JournalLineVO(
            line_id=uuid4(),
            journal_id=uuid4(),
            account_id=uuid4(),
            account_code="  acc-002  ",
            account_name="  cash  ",
            side=JournalSide.DEBIT,
            amount=Decimal("100.5"),
            description="  test  ",
            legal_entity_id=uuid4(),
            cost_center="  cc-01  ",
            department="  dept-a  ",
            currency="  usd  ",
        )
        norm = raw.normalize()
        assert norm.account_code == "ACC-002"
        assert norm.account_name == "Cash"
        assert norm.amount == Decimal("100.50")
        assert norm.description == "test"
        assert norm.cost_center == "CC-01"
        assert norm.department == "DEPT-A"
        assert norm.currency == "USD"

    def test_to_dict(self):
        instance = self._build_kwargs()
        line = JournalLineVO(**instance)
        d = line.to_dict()
        assert d["account_code"] == "ACC-001"
        assert d["amount"] == "100.00"
        assert d["side"] == "debit"
        assert d["tax_amount"] == "11.00"

    # --- from_dict ---
    def test_from_dict_minimal(self):
        data = {
            "journal_id": str(uuid4()),
            "account_id": str(uuid4()),
            "account_code": "ACC-001",
            "account_name": "Cash",
            "side": "debit",
            "amount": "100.00",
            "description": "Test",
            "legal_entity_id": str(uuid4()),
        }
        line = JournalLineVO.from_dict(data)
        assert line.journal_id == UUID(data["journal_id"])
        assert line.account_code == "ACC-001"
        assert line.side == JournalSide.DEBIT
        assert line.amount == Decimal("100.00")
        assert line.line_id is not None  # auto-generated

    def test_from_dict_full(self):
        line_id = uuid4()
        journal_id = uuid4()
        account_id = uuid4()
        legal_entity_id = uuid4()
        project_id = uuid4()
        customer_id = uuid4()
        supplier_id = uuid4()
        employee_id = uuid4()
        data = {
            "line_id": str(line_id),
            "journal_id": str(journal_id),
            "account_id": str(account_id),
            "account_code": "ACC-001",
            "account_name": "Cash",
            "side": "credit",
            "amount": "200.00",
            "description": "Test",
            "legal_entity_id": str(legal_entity_id),
            "cost_center": "CC-01",
            "department": "DEPT-A",
            "project_id": str(project_id),
            "customer_id": str(customer_id),
            "supplier_id": str(supplier_id),
            "employee_id": str(employee_id),
            "currency": "USD",
            "tax_rate": "11",
            "tax_amount": "22.00",
        }
        line = JournalLineVO.from_dict(data)
        assert line.line_id == line_id
        assert line.journal_id == journal_id
        assert line.account_id == account_id
        assert line.legal_entity_id == legal_entity_id
        assert line.side == JournalSide.CREDIT
        assert line.amount == Decimal("200.00")
        assert line.project_id == project_id
        assert line.customer_id == customer_id
        assert line.supplier_id == supplier_id
        assert line.employee_id == employee_id
        assert line.currency == "USD"
        assert line.tax_rate == Decimal("11")
        assert line.tax_amount == Decimal("22.00")

    def test_from_dict_side_from_string_variants(self):
        data = {
            "journal_id": str(uuid4()),
            "account_id": str(uuid4()),
            "account_code": "ACC",
            "account_name": "A",
            "side": "dr",
            "amount": "10",
            "description": "d",
            "legal_entity_id": str(uuid4()),
        }
        line = JournalLineVO.from_dict(data)
        assert line.side == JournalSide.DEBIT

        data["side"] = "cr"
        line2 = JournalLineVO.from_dict(data)
        assert line2.side == JournalSide.CREDIT

    # --- create_debit & create_credit ---
    def test_create_debit(self):
        journal_id = uuid4()
        account_id = uuid4()
        legal_entity_id = uuid4()
        line = JournalLineVO.create_debit(
            journal_id=journal_id,
            account_id=account_id,
            account_code="ACC-001",
            account_name="Cash",
            amount=Decimal("500"),
            description="Payment",
            legal_entity_id=legal_entity_id,
            cost_center="CC-01",
        )
        assert line.journal_id == journal_id
        assert line.account_id == account_id
        assert line.side == JournalSide.DEBIT
        assert line.amount == Decimal("500")
        assert line.cost_center == "CC-01"
        assert line.line_id is not None

    def test_create_credit(self):
        journal_id = uuid4()
        account_id = uuid4()
        legal_entity_id = uuid4()
        line = JournalLineVO.create_credit(
            journal_id=journal_id,
            account_id=account_id,
            account_code="ACC-002",
            account_name="Revenue",
            amount=Decimal("300"),
            description="Sale",
            legal_entity_id=legal_entity_id,
            department="DEPT-B",
        )
        assert line.journal_id == journal_id
        assert line.account_id == account_id
        assert line.side == JournalSide.CREDIT
        assert line.amount == Decimal("300")
        assert line.department == "DEPT-B"

    # --- __hash__, __eq__, to_string, from_string ---
    def test_hash(self):
        instance = self._build_kwargs()
        line1 = JournalLineVO(**instance)
        line2 = JournalLineVO(**instance)  # same data but different line_id? Actually line_id is same? We pass same line_id
        # We need two different objects with same line_id for equality
        line1 = JournalLineVO(**instance)
        # Create another with same line_id but different other fields
        same_id = line1.line_id
        line2 = JournalLineVO(
            line_id=same_id,
            journal_id=uuid4(),
            account_id=uuid4(),
            account_code="OTHER",
            account_name="Other",
            side=JournalSide.CREDIT,
            amount=Decimal("999"),
            description="Other",
            legal_entity_id=uuid4(),
        )
        assert hash(line1) == hash(line2)  # hash uses line_id, journal_id, account_id, side, amount
        # But we only defined __hash__ with line_id, journal_id, account_id, side, amount, so they should be equal if line_id same? Actually we only used those fields, so hash will be same.
        # Let's test __eq__ as well.

    def test_eq(self):
        line1 = JournalLineVO(**self._build_kwargs())
        line2 = JournalLineVO(**{**self._build_kwargs(), "line_id": line1.line_id})
        assert line1 == line2
        # Different line_id
        line3 = JournalLineVO(**{**self._build_kwargs(), "line_id": uuid4()})
        assert line1 != line3
        # Not JournalLineVO
        assert line1 != "string"

    def test_to_string(self):
        instance = self._build_kwargs()
        line = JournalLineVO(**instance)
        s = line.to_string()
        expected = "ACC-001|debit|100.00|Test entry"
        assert s == expected

    def test_from_string_valid(self):
        line = JournalLineVO.from_string("ACC-001|debit|100.00|Test entry")
        assert line.account_code == "ACC-001"
        assert line.side == JournalSide.DEBIT
        assert line.amount == Decimal("100.00")
        assert line.description == "Test entry"
        assert line.line_id is not None
        assert line.journal_id is not None

    def test_from_string_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid line string"):
            JournalLineVO.from_string("ACC-001|debit|100.00")  # missing description

    def test_from_string_invalid_side(self):
        with pytest.raises(ValueError, match="Invalid journal side"):
            JournalLineVO.from_string("ACC-001|invalid|100.00|desc")


class TestJournalLineRepository:
    """Tests for JournalLineRepository."""

    def _build_instance(self):
        return JournalLineRepository()

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, JournalLineRepository)

    async def test_get_by_journal(self):
        instance = self._build_instance()
        with pytest.raises(NotImplementedError):
            await instance.get_by_journal(journal_id=uuid4(), legal_entity_id=uuid4())

    async def test_get_by_account(self):
        instance = self._build_instance()
        with pytest.raises(NotImplementedError):
            await instance.get_by_account(
                account_id=uuid4(),
                legal_entity_id=uuid4(),
                from_date=datetime.now(UTC),
                to_date=datetime.now(UTC),
            )

    async def test_save(self):
        instance = self._build_instance()
        with pytest.raises(NotImplementedError):
            await instance.save(line=MagicMock())

    async def test_save_many(self):
        instance = self._build_instance()
        with pytest.raises(NotImplementedError):
            await instance.save_many(lines=[MagicMock()])

    async def test_delete_by_journal(self):
        instance = self._build_instance()
        with pytest.raises(NotImplementedError):
            await instance.delete_by_journal(journal_id=uuid4(), legal_entity_id=uuid4())
