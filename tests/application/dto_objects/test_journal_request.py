# tests/application/dto_objects/test_journal_request.py
"""
Comprehensive tests for application/dto_objects/journal_request.py
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from application.dto_objects.journal_request import (
    ApproveJournalRequest,
    CreateJournalRequest,
    GetJournalRequest,
    JournalEntryStatusDTO,
    JournalLineRequest,
    JournalQueryParams,
    JournalRequest,
    JournalRequestFactory,
    JournalResponseDTO,
    ListJournalsRequest,
    PostJournalRequest,
    RecurringJournalTemplateDTO,
    RejectJournalRequest,
    ReverseJournalRequest,
    SubmitJournalRequest,
    UpdateJournalRequest,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def account_id():
    return uuid4()


@pytest.fixture
def debit_line(account_id):
    return JournalLineRequest(
        account_id=account_id,
        account_code="1010",
        account_name="Cash",
        side="debit",
        amount=Decimal("1000"),
        description="Test debit",
    )


@pytest.fixture
def credit_line(account_id):
    return JournalLineRequest(
        account_id=account_id,
        account_code="4010",
        account_name="Revenue",
        side="credit",
        amount=Decimal("1000"),
        description="Test credit",
    )


@pytest.fixture
def two_lines(debit_line, credit_line):
    return [debit_line, credit_line]


@pytest.fixture
def create_request(two_lines):
    return CreateJournalRequest(
        journal_type="GENERAL",
        transaction_date=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
        description="Test journal",
        lines=two_lines,
        reference="REF-001",
        idempotency_key="idem-123",
        source_system="ERP",
    )


# ============================================================================
# Tests for JournalLineRequest
# ============================================================================

class TestJournalLineRequest:
    def test_construction_valid(self, account_id):
        line = JournalLineRequest(
            account_id=account_id,
            account_code="1010",
            account_name="Cash",
            side="debit",
            amount=Decimal("1000"),
            description="Test debit",
            cost_center="CC1",
            department="FIN",
            project_id=uuid4(),
        )
        assert line.account_id == account_id
        assert line.amount == Decimal("1000")
        assert line.is_debit() is True
        assert line.is_credit() is False

    def test_validation_zero_amount(self, account_id):
        with pytest.raises(ValueError, match="Amount must be positive"):
            JournalLineRequest(
                account_id=account_id,
                account_code="1010",
                account_name="Cash",
                side="debit",
                amount=Decimal("0"),
                description="Test",
            )

    def test_validation_negative_amount(self, account_id):
        with pytest.raises(ValueError, match="Amount must be positive"):
            JournalLineRequest(
                account_id=account_id,
                account_code="1010",
                account_name="Cash",
                side="debit",
                amount=Decimal("-100"),
                description="Test",
            )

    def test_validation_invalid_side(self, account_id):
        with pytest.raises(ValueError, match="Side must be 'debit' or 'credit'"):
            JournalLineRequest(
                account_id=account_id,
                account_code="1010",
                account_name="Cash",
                side="invalid",
                amount=Decimal("100"),
                description="Test",
            )

    def test_validation_missing_account_code(self, account_id):
        with pytest.raises(ValueError, match="Account code is required"):
            JournalLineRequest(
                account_id=account_id,
                account_code="",
                account_name="Cash",
                side="debit",
                amount=Decimal("100"),
                description="Test",
            )

    def test_validation_missing_description(self, account_id):
        with pytest.raises(ValueError, match="Description is required"):
            JournalLineRequest(
                account_id=account_id,
                account_code="1010",
                account_name="Cash",
                side="debit",
                amount=Decimal("100"),
                description="",
            )

    def test_is_debit_and_credit(self, account_id):
        line = JournalLineRequest(
            account_id=account_id,
            account_code="1010",
            account_name="Cash",
            side="debit",
            amount=Decimal("100"),
            description="Test",
        )
        assert line.is_debit() is True
        assert line.is_credit() is False
        # Credit
        line2 = JournalLineRequest(
            account_id=account_id,
            account_code="4010",
            account_name="Revenue",
            side="credit",
            amount=Decimal("100"),
            description="Test",
        )
        assert line2.is_debit() is False
        assert line2.is_credit() is True

    def test_to_dict(self, debit_line):
        d = debit_line.to_dict()
        assert d["account_id"] == str(debit_line.account_id)
        assert d["account_code"] == "1010"
        assert d["side"] == "debit"
        assert d["amount"] == "1000"
        assert d["description"] == "Test debit"
        assert "cost_center" in d

    def test_from_dict(self, account_id):
        data = {
            "account_id": str(account_id),
            "account_code": "2010",
            "account_name": "Accounts Payable",
            "side": "credit",
            "amount": "5000",
            "description": "AP accrual",
            "cost_center": "CC2",
            "department": "PUR",
            "project_id": str(uuid4()),
        }
        line = JournalLineRequest.from_dict(data)
        assert line.account_id == account_id
        assert line.account_code == "2010"
        assert line.amount == Decimal("5000")
        assert line.side == "credit"
        assert line.description == "AP accrual"
        assert line.cost_center == "CC2"
        assert line.department == "PUR"
        assert line.project_id is not None

    def test_from_dict_optional_fields_missing(self, account_id):
        data = {
            "account_id": str(account_id),
            "account_code": "1010",
            "account_name": "Cash",
            "side": "debit",
            "amount": "100",
            "description": "Test",
        }
        line = JournalLineRequest.from_dict(data)
        assert line.cost_center is None
        assert line.department is None
        assert line.project_id is None


# ============================================================================
# Tests for CreateJournalRequest
# ============================================================================

class TestCreateJournalRequest:
    def test_construction_valid(self, create_request, two_lines):
        assert create_request.journal_type == "GENERAL"
        assert create_request.description == "Test journal"
        assert len(create_request.lines) == 2
        assert create_request.idempotency_key == "idem-123"
        assert create_request.transaction_date.tzinfo is not None

    def test_validation_invalid_journal_type(self, two_lines):
        with pytest.raises(ValueError, match="Invalid journal_type"):
            CreateJournalRequest(
                journal_type="INVALID",
                transaction_date=datetime.now(UTC),
                description="Test",
                lines=two_lines,
            )

    def test_validation_description_too_short(self, two_lines):
        with pytest.raises(ValueError, match="Description must be at least 3 characters"):
            CreateJournalRequest(
                journal_type="GENERAL",
                transaction_date=datetime.now(UTC),
                description="AB",
                lines=two_lines,
            )

    def test_validation_less_than_two_lines(self, account_id):
        one_line = JournalLineRequest(
            account_id=account_id,
            account_code="1010",
            account_name="Cash",
            side="debit",
            amount=Decimal("100"),
            description="Test",
        )
        with pytest.raises(ValueError, match="Journal must have at least 2 lines"):
            CreateJournalRequest(
                journal_type="GENERAL",
                transaction_date=datetime.now(UTC),
                description="Test",
                lines=[one_line],
            )

    def test_validation_auto_timezone(self):
        naive = datetime(2026, 1, 15, 12, 0, 0)
        request = CreateJournalRequest(
            journal_type="GENERAL",
            transaction_date=naive,
            description="Test",
            lines=[],  # will fail lines validation, but we just check tz
        )
        # __post_init__ runs tz conversion before lines validation, so we need to catch ValueError
        with pytest.raises(ValueError):  # lines validation will raise, but tz was set
            pass

    def test_calculate_total_debit(self, debit_line, credit_line):
        request = CreateJournalRequest(
            journal_type="GENERAL",
            transaction_date=datetime.now(UTC),
            description="Test",
            lines=[debit_line, credit_line],
        )
        assert request.calculate_total_debit() == Decimal("1000")

        # Add another debit line
        debit_line2 = JournalLineRequest(
            account_id=uuid4(),
            account_code="1020",
            account_name="Bank",
            side="debit",
            amount=Decimal("500"),
            description="Test",
        )
        request.lines.append(debit_line2)
        assert request.calculate_total_debit() == Decimal("1500")

    def test_calculate_total_credit(self, debit_line, credit_line):
        request = CreateJournalRequest(
            journal_type="GENERAL",
            transaction_date=datetime.now(UTC),
            description="Test",
            lines=[debit_line, credit_line],
        )
        assert request.calculate_total_credit() == Decimal("1000")

        # Add another credit line
        credit_line2 = JournalLineRequest(
            account_id=uuid4(),
            account_code="4020",
            account_name="Interest Income",
            side="credit",
            amount=Decimal("200"),
            description="Test",
        )
        request.lines.append(credit_line2)
        assert request.calculate_total_credit() == Decimal("1200")

    def test_is_balanced_true(self, debit_line, credit_line):
        request = CreateJournalRequest(
            journal_type="GENERAL",
            transaction_date=datetime.now(UTC),
            description="Test",
            lines=[debit_line, credit_line],
        )
        assert request.is_balanced() is True

    def test_is_balanced_false(self, debit_line):
        # Only one line, but still validation would catch; we'll create with two but unequal
        credit_line = JournalLineRequest(
            account_id=uuid4(),
            account_code="4010",
            account_name="Revenue",
            side="credit",
            amount=Decimal("800"),  # not equal to debit 1000
            description="Test",
        )
        request = CreateJournalRequest(
            journal_type="GENERAL",
            transaction_date=datetime.now(UTC),
            description="Test",
            lines=[debit_line, credit_line],
        )
        assert request.is_balanced() is False

    def test_is_balanced_with_tolerance(self, debit_line):
        credit_line = JournalLineRequest(
            account_id=uuid4(),
            account_code="4010",
            account_name="Revenue",
            side="credit",
            amount=Decimal("999.9999"),
            description="Test",
        )
        request = CreateJournalRequest(
            journal_type="GENERAL",
            transaction_date=datetime.now(UTC),
            description="Test",
            lines=[debit_line, credit_line],
        )
        # Default tolerance 0.0001: difference 0.0001 <= 0.0001 -> balanced
        assert request.is_balanced() is True
        # With smaller tolerance
        assert request.is_balanced(tolerance=Decimal("0.00001")) is False

    def test_to_dict(self, create_request):
        d = create_request.to_dict()
        assert d["journal_type"] == "GENERAL"
        assert d["description"] == "Test journal"
        assert d["reference"] == "REF-001"
        assert d["idempotency_key"] == "idem-123"
        assert d["source_system"] == "ERP"
        assert d["total_debit"] == "1000"
        assert d["total_credit"] == "1000"
        assert d["is_balanced"] is True
        assert len(d["lines"]) == 2

    def test_from_dict(self, account_id):
        data = {
            "journal_type": "ADJUSTING",
            "transaction_date": "2026-01-15T12:00:00+00:00",
            "description": "Adjusting entry",
            "lines": [
                {
                    "account_id": str(account_id),
                    "account_code": "1010",
                    "account_name": "Cash",
                    "side": "debit",
                    "amount": "500",
                    "description": "Debit line",
                },
                {
                    "account_id": str(account_id),
                    "account_code": "4010",
                    "account_name": "Revenue",
                    "side": "credit",
                    "amount": "500",
                    "description": "Credit line",
                },
            ],
            "reference": "REF-002",
            "idempotency_key": "idem-456",
            "source_system": "MANUAL",
        }
        request = CreateJournalRequest.from_dict(data)
        assert request.journal_type == "ADJUSTING"
        assert request.description == "Adjusting entry"
        assert len(request.lines) == 2
        assert request.reference == "REF-002"
        assert request.idempotency_key == "idem-456"
        assert request.source_system == "MANUAL"
        assert request.transaction_date == datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
        assert request.is_balanced() is True


# ============================================================================
# Tests for UpdateJournalRequest
# ============================================================================

class TestUpdateJournalRequest:
    def test_construction_valid(self):
        req = UpdateJournalRequest(
            journal_id=uuid4(),
            description="Updated desc",
            reference="REF-NEW",
        )
        assert req.description == "Updated desc"
        assert req.reference == "REF-NEW"
        assert req.lines is None

    def test_construction_with_lines(self, debit_line, credit_line):
        req = UpdateJournalRequest(
            journal_id=uuid4(),
            lines=[debit_line, credit_line],
        )
        assert len(req.lines) == 2

    def test_validation_no_fields(self):
        with pytest.raises(ValueError, match="At least one field to update"):
            UpdateJournalRequest(journal_id=uuid4())

    def test_validation_description_too_short(self):
        with pytest.raises(ValueError, match="Description must be at least 3 characters"):
            UpdateJournalRequest(
                journal_id=uuid4(),
                description="AB",
            )

    def test_to_dict(self):
        journal_id = uuid4()
        req = UpdateJournalRequest(
            journal_id=journal_id,
            description="New desc",
            reference="REF-003",
        )
        d = req.to_dict()
        assert d["journal_id"] == str(journal_id)
        assert d["description"] == "New desc"
        assert d["reference"] == "REF-003"
        assert d["lines"] is None

    def test_to_dict_with_lines(self, debit_line, credit_line):
        journal_id = uuid4()
        req = UpdateJournalRequest(
            journal_id=journal_id,
            lines=[debit_line, credit_line],
        )
        d = req.to_dict()
        assert len(d["lines"]) == 2


# ============================================================================
# Tests for SubmitJournalRequest
# ============================================================================

class TestSubmitJournalRequest:
    def test_construction_valid(self):
        req = SubmitJournalRequest(
            journal_id=uuid4(),
            submitted_by="user1",
            notes="Please approve",
        )
        assert req.submitted_by == "user1"
        assert req.notes == "Please approve"

    def test_validation_missing_submitted_by(self):
        with pytest.raises(ValueError, match="submitted_by is required"):
            SubmitJournalRequest(journal_id=uuid4(), submitted_by="")

    def test_to_dict(self):
        journal_id = uuid4()
        req = SubmitJournalRequest(
            journal_id=journal_id,
            submitted_by="user2",
            notes="Notes",
        )
        d = req.to_dict()
        assert d["journal_id"] == str(journal_id)
        assert d["submitted_by"] == "user2"
        assert d["notes"] == "Notes"


# ============================================================================
# Tests for ApproveJournalRequest
# ============================================================================

class TestApproveJournalRequest:
    def test_construction_valid(self):
        req = ApproveJournalRequest(
            journal_id=uuid4(),
            approved_by="approver1",
            approval_level=2,
            notes="Approved",
        )
        assert req.approved_by == "approver1"
        assert req.approval_level == 2

    def test_validation_missing_approved_by(self):
        with pytest.raises(ValueError, match="approved_by is required"):
            ApproveJournalRequest(journal_id=uuid4(), approved_by="")

    def test_validation_approval_level_zero(self):
        with pytest.raises(ValueError, match="approval_level must be at least 1"):
            ApproveJournalRequest(journal_id=uuid4(), approved_by="a", approval_level=0)

    def test_to_dict(self):
        journal_id = uuid4()
        req = ApproveJournalRequest(
            journal_id=journal_id,
            approved_by="a",
            approval_level=3,
            notes="OK",
        )
        d = req.to_dict()
        assert d["journal_id"] == str(journal_id)
        assert d["approved_by"] == "a"
        assert d["approval_level"] == 3
        assert d["notes"] == "OK"


# ============================================================================
# Tests for RejectJournalRequest
# ============================================================================

class TestRejectJournalRequest:
    def test_construction_valid(self):
        req = RejectJournalRequest(
            journal_id=uuid4(),
            rejected_by="rejector",
            reason="Incorrect amount",
        )
        assert req.rejected_by == "rejector"
        assert req.reason == "Incorrect amount"

    def test_validation_missing_rejected_by(self):
        with pytest.raises(ValueError, match="rejected_by is required"):
            RejectJournalRequest(journal_id=uuid4(), rejected_by="", reason="r")

    def test_validation_reason_too_short(self):
        with pytest.raises(ValueError, match="Reason must be at least 5 characters"):
            RejectJournalRequest(journal_id=uuid4(), rejected_by="a", reason="abc")

    def test_to_dict(self):
        journal_id = uuid4()
        req = RejectJournalRequest(
            journal_id=journal_id,
            rejected_by="r",
            reason="Invalid data",
        )
        d = req.to_dict()
        assert d["journal_id"] == str(journal_id)
        assert d["rejected_by"] == "r"
        assert d["reason"] == "Invalid data"


# ============================================================================
# Tests for PostJournalRequest
# ============================================================================

class TestPostJournalRequest:
    def test_construction_valid(self):
        req = PostJournalRequest(
            journal_id=uuid4(),
            posted_by="poster",
            force_post=True,
        )
        assert req.posted_by == "poster"
        assert req.force_post is True

    def test_validation_missing_posted_by(self):
        with pytest.raises(ValueError, match="posted_by is required"):
            PostJournalRequest(journal_id=uuid4(), posted_by="")

    def test_to_dict(self):
        journal_id = uuid4()
        req = PostJournalRequest(
            journal_id=journal_id,
            posted_by="p",
            force_post=False,
        )
        d = req.to_dict()
        assert d["journal_id"] == str(journal_id)
        assert d["posted_by"] == "p"
        assert d["force_post"] is False


# ============================================================================
# Tests for ReverseJournalRequest
# ============================================================================

class TestReverseJournalRequest:
    def test_construction_valid(self):
        req = ReverseJournalRequest(
            journal_id=uuid4(),
            reversed_by="reverser",
            reason="Correction",
            reversal_date=datetime(2026, 1, 16, 12, 0, 0, tzinfo=UTC),
        )
        assert req.reversed_by == "reverser"
        assert req.reason == "Correction"
        assert req.reversal_date == datetime(2026, 1, 16, 12, 0, 0, tzinfo=UTC)

    def test_auto_reversal_date(self):
        req = ReverseJournalRequest(
            journal_id=uuid4(),
            reversed_by="r",
            reason="Auto date",
            reversal_date=None,
        )
        assert req.reversal_date is not None
        assert req.reversal_date.tzinfo is not None

    def test_validation_missing_reversed_by(self):
        with pytest.raises(ValueError, match="reversed_by is required"):
            ReverseJournalRequest(journal_id=uuid4(), reversed_by="", reason="r")

    def test_validation_reason_too_short(self):
        with pytest.raises(ValueError, match="Reason must be at least 5 characters"):
            ReverseJournalRequest(journal_id=uuid4(), reversed_by="a", reason="abc")

    def test_auto_timezone(self):
        naive = datetime(2026, 1, 16, 12, 0, 0)
        req = ReverseJournalRequest(
            journal_id=uuid4(),
            reversed_by="r",
            reason="Tz conversion",
            reversal_date=naive,
        )
        assert req.reversal_date.tzinfo is not None

    def test_to_dict(self):
        journal_id = uuid4()
        req = ReverseJournalRequest(
            journal_id=journal_id,
            reversed_by="r",
            reason="Reverse",
            reversal_date=datetime(2026, 1, 17, 12, 0, 0, tzinfo=UTC),
        )
        d = req.to_dict()
        assert d["journal_id"] == str(journal_id)
        assert d["reversed_by"] == "r"
        assert d["reason"] == "Reverse"
        assert "reversal_date" in d


# ============================================================================
# Tests for GetJournalRequest
# ============================================================================

class TestGetJournalRequest:
    def test_construction(self):
        journal_id = uuid4()
        le_id = uuid4()
        req = GetJournalRequest(journal_id=journal_id, legal_entity_id=le_id)
        assert req.journal_id == journal_id
        assert req.legal_entity_id == le_id

    def test_to_dict(self):
        journal_id = uuid4()
        le_id = uuid4()
        req = GetJournalRequest(journal_id=journal_id, legal_entity_id=le_id)
        d = req.to_dict()
        assert d["journal_id"] == str(journal_id)
        assert d["legal_entity_id"] == str(le_id)


# ============================================================================
# Tests for ListJournalsRequest
# ============================================================================

class TestListJournalsRequest:
    def test_construction_valid(self):
        le_id = uuid4()
        req = ListJournalsRequest(
            legal_entity_id=le_id,
            from_date=datetime(2026, 1, 1, tzinfo=UTC),
            to_date=datetime(2026, 1, 31, tzinfo=UTC),
            journal_type="GENERAL",
            status="POSTED",
            created_by="user",
            limit=50,
            offset=10,
        )
        assert req.legal_entity_id == le_id
        assert req.limit == 50
        assert req.offset == 10

    def test_validation_limit_range(self):
        le_id = uuid4()
        with pytest.raises(ValueError, match="limit must be between 1 and 1000"):
            ListJournalsRequest(legal_entity_id=le_id, limit=0)
        with pytest.raises(ValueError, match="limit must be between 1 and 1000"):
            ListJournalsRequest(legal_entity_id=le_id, limit=1001)

    def test_validation_offset_negative(self):
        le_id = uuid4()
        with pytest.raises(ValueError, match="offset must be >= 0"):
            ListJournalsRequest(legal_entity_id=le_id, offset=-1)

    def test_validation_invalid_journal_type(self):
        le_id = uuid4()
        with pytest.raises(ValueError, match="Invalid journal_type"):
            ListJournalsRequest(legal_entity_id=le_id, journal_type="INVALID")

    def test_auto_timezone(self):
        le_id = uuid4()
        naive_from = datetime(2026, 1, 1, 0, 0, 0)
        req = ListJournalsRequest(legal_entity_id=le_id, from_date=naive_from)
        assert req.from_date.tzinfo is not None

    def test_to_dict(self):
        le_id = uuid4()
        req = ListJournalsRequest(
            legal_entity_id=le_id,
            from_date=datetime(2026, 1, 1, tzinfo=UTC),
            to_date=datetime(2026, 1, 31, tzinfo=UTC),
            journal_type="GENERAL",
            status="DRAFT",
            created_by="u",
            limit=20,
            offset=5,
        )
        d = req.to_dict()
        assert d["legal_entity_id"] == str(le_id)
        assert d["from_date"] == "2026-01-01T00:00:00+00:00"
        assert d["to_date"] == "2026-01-31T00:00:00+00:00"
        assert d["journal_type"] == "GENERAL"
        assert d["status"] == "DRAFT"
        assert d["created_by"] == "u"
        assert d["limit"] == 20
        assert d["offset"] == 5


# ============================================================================
# Tests for JournalQueryParams
# ============================================================================

class TestJournalQueryParams:
    def test_construction_valid(self):
        le_id = uuid4()
        params = JournalQueryParams(
            legal_entity_id=le_id,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            end_date=datetime(2026, 1, 31, tzinfo=UTC),
            journal_type="ADJUSTING",
            status="POSTED",
            page=2,
            per_page=30,
        )
        assert params.legal_entity_id == le_id
        assert params.page == 2
        assert params.per_page == 30

    def test_auto_timezone(self):
        le_id = uuid4()
        naive = datetime(2026, 1, 1, 0, 0, 0)
        params = JournalQueryParams(legal_entity_id=le_id, start_date=naive)
        assert params.start_date.tzinfo is not None

    def test_get_offset(self):
        params = JournalQueryParams(legal_entity_id=uuid4(), page=3, per_page=15)
        assert params.get_offset() == 30  # (3-1)*15

    def test_get_offset_default(self):
        params = JournalQueryParams(legal_entity_id=uuid4())
        assert params.get_offset() == 0  # page=1, per_page=20 -> (1-1)*20=0

    def test_to_dict(self):
        le_id = uuid4()
        params = JournalQueryParams(
            legal_entity_id=le_id,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            end_date=datetime(2026, 1, 31, tzinfo=UTC),
            journal_type="REVERSAL",
            status="DRAFT",
            page=3,
            per_page=25,
        )
        d = params.to_dict()
        assert d["legal_entity_id"] == str(le_id)
        assert d["start_date"] == "2026-01-01T00:00:00+00:00"
        assert d["end_date"] == "2026-01-31T00:00:00+00:00"
        assert d["journal_type"] == "REVERSAL"
        assert d["status"] == "DRAFT"
        assert d["page"] == 3
        assert d["per_page"] == 25


# ============================================================================
# Tests for RecurringJournalTemplateDTO
# ============================================================================

class TestRecurringJournalTemplateDTO:
    def test_construction(self, debit_line, credit_line):
        template_id = uuid4()
        dto = RecurringJournalTemplateDTO(
            template_id=template_id,
            template_name="Monthly Accrual",
            description="Accrual template",
            schedule_type="MONTHLY",
            lines=[debit_line, credit_line],
            is_active=True,
        )
        assert dto.template_id == template_id
        assert dto.template_name == "Monthly Accrual"
        assert dto.is_active is True

    def test_to_dict(self, debit_line, credit_line):
        template_id = uuid4()
        dto = RecurringJournalTemplateDTO(
            template_id=template_id,
            template_name="Weekly",
            description="Weekly template",
            schedule_type="WEEKLY",
            lines=[debit_line, credit_line],
            is_active=False,
        )
        d = dto.to_dict()
        assert d["template_id"] == str(template_id)
        assert d["template_name"] == "Weekly"
        assert d["schedule_type"] == "WEEKLY"
        assert d["is_active"] is False
        assert len(d["lines"]) == 2


# ============================================================================
# Tests for JournalEntryStatusDTO
# ============================================================================

class TestJournalEntryStatusDTO:
    def test_members(self):
        assert JournalEntryStatusDTO.DRAFT.value == "draft"
        assert JournalEntryStatusDTO.POSTED.value == "posted"


# ============================================================================
# Tests for JournalResponseDTO
# ============================================================================

class TestJournalResponseDTO:
    def test_construction(self):
        journal_id = uuid4()
        line = MagicMock(spec=JournalLineRequest)
        dto = JournalResponseDTO(
            id=journal_id,
            journal_number="JRN-001",
            journal_date=date(2026, 1, 15),
            period="2026-01",
            description="Test",
            total_debit=Decimal("1000"),
            total_credit=Decimal("1000"),
            lines=[line],
            approved_at=datetime(2026, 1, 16, tzinfo=UTC),
            status=JournalEntryStatusDTO.APPROVED,
            created_by="user",
            approved_by="approver",
            version=2,
        )
        assert dto.id == journal_id
        assert dto.journal_number == "JRN-001"
        assert dto.status == JournalEntryStatusDTO.APPROVED
        assert dto.version == 2

    def test_default_created_at(self):
        dto = JournalResponseDTO(
            id=uuid4(),
            journal_number="JRN-002",
            journal_date=date.today(),
            period="2026-01",
            description="Test",
            total_debit=Decimal("0"),
            total_credit=Decimal("0"),
            lines=[],
        )
        assert dto.created_at is not None
        assert dto.created_at.tzinfo is not None


# ============================================================================
# Tests for JournalRequest (simple test compatibility)
# ============================================================================

class TestJournalRequest:
    def test_construction(self):
        lines = [
            {"account": "1010", "debit": "100", "credit": "0"},
            {"account": "4010", "debit": "0", "credit": "100"},
        ]
        req = JournalRequest(description="Test", lines=lines)
        assert req.description == "Test"
        assert len(req.lines) == 2
        assert req.lines[0].account == "1010"
        assert req.lines[0].debit == Decimal("100")
        assert req.lines[0].credit == Decimal("0")

    def test_is_valid_true(self):
        lines = [
            {"account": "1010", "debit": "100", "credit": "0"},
            {"account": "4010", "debit": "0", "credit": "100"},
        ]
        req = JournalRequest(description="Test", lines=lines)
        assert req.is_valid() is True

    def test_is_valid_false(self):
        lines = [{"account": "1010", "debit": "100", "credit": "0"}]
        req = JournalRequest(description="Test", lines=lines)
        assert req.is_valid() is False

    def test_handles_missing_fields(self):
        lines = [{"account": "1010"}]  # missing debit/credit
        req = JournalRequest(description="Test", lines=lines)
        assert req.lines[0].debit == Decimal("0")
        assert req.lines[0].credit == Decimal("0")
        # is_valid still false because only one line
        assert req.is_valid() is False


# ============================================================================
# Tests for JournalRequestFactory
# ============================================================================

class TestJournalRequestFactory:
    def test_create_journal_line(self, account_id):
        line = JournalRequestFactory.create_journal_line(
            account_id=account_id,
            account_code="1010",
            account_name="Cash",
            side="debit",
            amount=Decimal("100"),
            description="Test",
            cost_center="CC1",
            department="FIN",
            project_id=uuid4(),
        )
        assert line.account_id == account_id
        assert line.side == "debit"

    def test_create_debit_line(self, account_id):
        line = JournalRequestFactory.create_debit_line(
            account_id=account_id,
            account_code="1010",
            account_name="Cash",
            amount=Decimal("500"),
            description="Test debit",
            cost_center="CC2",
        )
        assert line.side == "debit"
        assert line.amount == Decimal("500")
        assert line.cost_center == "CC2"

    def test_create_credit_line(self, account_id):
        line = JournalRequestFactory.create_credit_line(
            account_id=account_id,
            account_code="4010",
            account_name="Revenue",
            amount=Decimal("800"),
            description="Test credit",
            department="SALES",
        )
        assert line.side == "credit"
        assert line.amount == Decimal("800")
        assert line.department == "SALES"

    def test_create_simple_journal(self, account_id):
        debit_id = account_id
        credit_id = uuid4()
        request = JournalRequestFactory.create_simple_journal(
            journal_type="GENERAL",
            transaction_date=datetime(2026, 1, 15, tzinfo=UTC),
            description="Simple journal",
            debit_account_id=debit_id,
            debit_account_code="1010",
            debit_account_name="Cash",
            credit_account_id=credit_id,
            credit_account_code="4010",
            credit_account_name="Revenue",
            amount=Decimal("1000"),
            reference="REF-001",
        )
        assert request.journal_type == "GENERAL"
        assert request.description == "Simple journal"
        assert len(request.lines) == 2
        assert request.lines[0].side == "debit"
        assert request.lines[0].amount == Decimal("1000")
        assert request.lines[1].side == "credit"
        assert request.lines[1].amount == Decimal("1000")
        assert request.reference == "REF-001"
        assert request.is_balanced() is True
