# test_account_dto.py
# Comprehensive tests for application/dto_objects/account_dto.py

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from application.dto_objects.account_dto import (
    AccountBalanceResponse,
    AccountDTOFactory,
    AccountHierarchyNodeDTO,
    AccountNormalBalance,
    AccountResponse,
    AccountStatusDTO,
    AccountTypeDTO,
    AccountValidationResult,
    BulkImportResultDTO,
    CreateAccountRequest,
    GetAccountByCodeRequest,
    GetAccountRequest,
    GetAccountsQuery,
    UpdateAccountRequest,
)


# -------------------- Fixtures --------------------
@pytest.fixture
def sample_legal_entity_id():
    return uuid4()


@pytest.fixture
def sample_account_id():
    return uuid4()


@pytest.fixture
def sample_parent_id():
    return uuid4()


@pytest.fixture
def sample_create_request(sample_legal_entity_id, sample_parent_id):
    return CreateAccountRequest(
        legal_entity_id=sample_legal_entity_id,
        account_code="1000",
        name="Cash",
        account_type="ASSET",
        parent_account_id=sample_parent_id,
        description="Cash account",
        opening_balance=Decimal("1000000"),
        currency_code="IDR",
        is_header=False,
        is_active=True,
        tax_code="PPN",
        financial_report_section="Current Assets",
    )


@pytest.fixture
def sample_update_request(sample_account_id):
    return UpdateAccountRequest(
        account_id=sample_account_id,
        name="Updated Cash",
        description="Updated description",
        parent_account_id=None,
        opening_balance=Decimal("2000000"),
        status="INACTIVE",
        deactivation_reason="Closed",
        tax_code="PPN",
        financial_report_section="Non-Current Assets",
    )


@pytest.fixture
def sample_account_response(sample_account_id, sample_legal_entity_id):
    return AccountResponse(
        id=sample_account_id,
        legal_entity_id=sample_legal_entity_id,
        account_code="1000",
        name="Cash",
        account_type="ASSET",
        normal_balance="debit",
        parent_account_id=None,
        description="Cash account",
        opening_balance=Decimal("1000000"),
        currency_code="IDR",
        is_header=False,
        level=1,
        status="ACTIVE",
        created_at=datetime.now(UTC),
        created_by=uuid4(),
        updated_at=datetime.now(UTC),
        updated_by=uuid4(),
        version=1,
        tax_code="PPN",
        financial_report_section="Current Assets",
        current_balance=Decimal("1500000"),
    )


@pytest.fixture
def sample_hierarchy_node():
    return AccountHierarchyNodeDTO(
        id=uuid4(),
        account_code="1000",
        name="Cash",
        account_type="ASSET",
        normal_balance="debit",
        level=1,
        children=[],
        is_header=False,
        status="ACTIVE",
        opening_balance=Decimal("1000000"),
        current_balance=Decimal("1500000"),
        description="Cash account",
    )


@pytest.fixture
def sample_balance_response(sample_account_id):
    return AccountBalanceResponse(
        account_id=sample_account_id,
        account_code="1000",
        account_name="Cash",
        opening_balance=Decimal("1000000"),
        period_debit=Decimal("500000"),
        period_credit=Decimal("200000"),
        ending_balance=Decimal("1300000"),
        normal_balance="debit",
        period_start=datetime.now(UTC) - timedelta(days=30),
        period_end=datetime.now(UTC),
        currency_code="IDR",
    )


# -------------------- Tests for Enums --------------------
class TestEnums:
    def test_account_type_dto_get_normal_balance(self):
        assert AccountTypeDTO.get_normal_balance("ASSET") == "debit"
        assert AccountTypeDTO.get_normal_balance("CONTRA_ASSET") == "credit"
        assert AccountTypeDTO.get_normal_balance("LIABILITY") == "credit"
        assert AccountTypeDTO.get_normal_balance("CONTRA_LIABILITY") == "debit"
        assert AccountTypeDTO.get_normal_balance("EQUITY") == "credit"
        assert AccountTypeDTO.get_normal_balance("CONTRA_EQUITY") == "debit"
        assert AccountTypeDTO.get_normal_balance("REVENUE") == "credit"
        assert AccountTypeDTO.get_normal_balance("EXPENSE") == "debit"
        # Unknown type defaults to debit
        assert AccountTypeDTO.get_normal_balance("UNKNOWN") == "debit"

    def test_account_type_dto_is_asset(self):
        assert AccountTypeDTO.ASSET.is_asset() is True
        assert AccountTypeDTO.CONTRA_ASSET.is_asset() is True
        assert AccountTypeDTO.LIABILITY.is_asset() is False
        assert AccountTypeDTO.EQUITY.is_asset() is False
        assert AccountTypeDTO.REVENUE.is_asset() is False

    def test_account_type_dto_is_liability(self):
        assert AccountTypeDTO.LIABILITY.is_liability() is True
        assert AccountTypeDTO.CONTRA_LIABILITY.is_liability() is True
        assert AccountTypeDTO.ASSET.is_liability() is False
        assert AccountTypeDTO.EQUITY.is_liability() is False

    def test_account_type_dto_is_equity(self):
        assert AccountTypeDTO.EQUITY.is_equity() is True
        assert AccountTypeDTO.CONTRA_EQUITY.is_equity() is True
        assert AccountTypeDTO.ASSET.is_equity() is False
        assert AccountTypeDTO.LIABILITY.is_equity() is False

    def test_account_type_dto_is_income_statement(self):
        assert AccountTypeDTO.REVENUE.is_income_statement() is True
        assert AccountTypeDTO.EXPENSE.is_income_statement() is True
        assert AccountTypeDTO.ASSET.is_income_statement() is False

    def test_account_type_dto_is_balance_sheet(self):
        assert AccountTypeDTO.ASSET.is_balance_sheet() is True
        assert AccountTypeDTO.LIABILITY.is_balance_sheet() is True
        assert AccountTypeDTO.EQUITY.is_balance_sheet() is True
        assert AccountTypeDTO.CONTRA_ASSET.is_balance_sheet() is True
        assert AccountTypeDTO.CONTRA_LIABILITY.is_balance_sheet() is True
        assert AccountTypeDTO.CONTRA_EQUITY.is_balance_sheet() is True
        assert AccountTypeDTO.REVENUE.is_balance_sheet() is False
        assert AccountTypeDTO.EXPENSE.is_balance_sheet() is False

    def test_account_status_dto_is_active(self):
        assert AccountStatusDTO.ACTIVE.is_active() is True
        assert AccountStatusDTO.INACTIVE.is_active() is False
        assert AccountStatusDTO.LOCKED.is_active() is False
        assert AccountStatusDTO.CLOSED.is_active() is False

    def test_account_status_dto_can_post(self):
        assert AccountStatusDTO.ACTIVE.can_post() is True
        assert AccountStatusDTO.INACTIVE.can_post() is True
        assert AccountStatusDTO.LOCKED.can_post() is False
        assert AccountStatusDTO.CLOSED.can_post() is False

    def test_account_normal_balance_opposite(self):
        assert AccountNormalBalance.DEBIT.opposite() == AccountNormalBalance.CREDIT
        assert AccountNormalBalance.CREDIT.opposite() == AccountNormalBalance.DEBIT


# -------------------- Tests for CreateAccountRequest --------------------
class TestCreateAccountRequest:
    def test_construction_valid(self, sample_create_request):
        assert sample_create_request.legal_entity_id is not None
        assert sample_create_request.account_code == "1000"
        assert sample_create_request.name == "Cash"
        assert sample_create_request.account_type == "ASSET"
        assert sample_create_request.parent_account_id is not None
        assert sample_create_request.opening_balance == Decimal("1000000")
        assert sample_create_request.is_active is True

    def test_validation_account_code_short(self, sample_legal_entity_id):
        with pytest.raises(ValueError, match="Account code must be at least 3 characters"):
            CreateAccountRequest(
                legal_entity_id=sample_legal_entity_id,
                account_code="AB",
                name="Test",
                account_type="ASSET",
            )

    def test_validation_name_short(self, sample_legal_entity_id):
        with pytest.raises(ValueError, match="Account name must be at least 2 characters"):
            CreateAccountRequest(
                legal_entity_id=sample_legal_entity_id,
                account_code="1000",
                name="A",
                account_type="ASSET",
            )

    def test_validation_account_type_invalid(self, sample_legal_entity_id):
        with pytest.raises(ValueError, match="Invalid account_type"):
            CreateAccountRequest(
                legal_entity_id=sample_legal_entity_id,
                account_code="1000",
                name="Test",
                account_type="INVALID",
            )

    def test_validation_opening_balance_negative(self, sample_legal_entity_id):
        with pytest.raises(ValueError, match="Opening balance cannot be negative"):
            CreateAccountRequest(
                legal_entity_id=sample_legal_entity_id,
                account_code="1000",
                name="Test",
                account_type="ASSET",
                opening_balance=Decimal("-100"),
            )

    def test_validation_currency_invalid(self, sample_legal_entity_id):
        with pytest.raises(ValueError, match="Invalid currency_code"):
            CreateAccountRequest(
                legal_entity_id=sample_legal_entity_id,
                account_code="1000",
                name="Test",
                account_type="ASSET",
                currency_code="XYZ",
            )

    def test_get_normal_balance(self, sample_create_request):
        assert sample_create_request.get_normal_balance() == "debit"

    def test_to_dict(self, sample_create_request):
        d = sample_create_request.to_dict()
        assert d["legal_entity_id"] == str(sample_create_request.legal_entity_id)
        assert d["account_code"] == "1000"
        assert d["name"] == "Cash"
        assert d["account_type"] == "ASSET"
        assert d["parent_account_id"] == str(sample_create_request.parent_account_id)
        assert d["opening_balance"] == "1000000"
        assert d["currency_code"] == "IDR"
        assert d["is_active"] is True
        assert d["normal_balance"] == "debit"

    def test_from_dict(self, sample_create_request):
        d = sample_create_request.to_dict()
        restored = CreateAccountRequest.from_dict(d)
        assert restored.legal_entity_id == sample_create_request.legal_entity_id
        assert restored.account_code == sample_create_request.account_code
        assert restored.name == sample_create_request.name
        assert restored.account_type == sample_create_request.account_type
        assert restored.parent_account_id == sample_create_request.parent_account_id
        assert restored.opening_balance == sample_create_request.opening_balance
        assert restored.currency_code == sample_create_request.currency_code
        assert restored.is_active == sample_create_request.is_active
        assert restored.tax_code == sample_create_request.tax_code
        assert restored.financial_report_section == sample_create_request.financial_report_section


# -------------------- Tests for UpdateAccountRequest --------------------
class TestUpdateAccountRequest:
    def test_construction_valid(self, sample_update_request):
        assert sample_update_request.account_id is not None
        assert sample_update_request.name == "Updated Cash"
        assert sample_update_request.status == "INACTIVE"

    def test_validation_at_least_one_field(self, sample_account_id):
        with pytest.raises(ValueError, match="At least one field to update must be provided"):
            UpdateAccountRequest(account_id=sample_account_id)

    def test_validation_name_too_short(self, sample_account_id):
        with pytest.raises(ValueError, match="Account name must be at least 2 characters"):
            UpdateAccountRequest(account_id=sample_account_id, name="A")

    def test_validation_status_invalid(self, sample_account_id):
        with pytest.raises(ValueError, match="Invalid status"):
            UpdateAccountRequest(account_id=sample_account_id, status="INVALID")

    def test_validation_opening_balance_negative(self, sample_account_id):
        with pytest.raises(ValueError, match="Opening balance cannot be negative"):
            UpdateAccountRequest(account_id=sample_account_id, opening_balance=Decimal("-10"))

    def test_to_dict(self, sample_update_request):
        d = sample_update_request.to_dict()
        assert d["account_id"] == str(sample_update_request.account_id)
        assert d["name"] == "Updated Cash"
        assert d["description"] == "Updated description"
        assert d["parent_account_id"] is None
        assert d["opening_balance"] == "2000000"
        assert d["status"] == "INACTIVE"
        assert d["deactivation_reason"] == "Closed"
        assert d["tax_code"] == "PPN"
        assert d["financial_report_section"] == "Non-Current Assets"


# -------------------- Tests for GetAccountRequest --------------------
class TestGetAccountRequest:
    def test_construction(self, sample_account_id, sample_legal_entity_id):
        req = GetAccountRequest(account_id=sample_account_id, legal_entity_id=sample_legal_entity_id)
        assert req.account_id == sample_account_id
        assert req.legal_entity_id == sample_legal_entity_id

    def test_to_dict(self, sample_account_id, sample_legal_entity_id):
        req = GetAccountRequest(account_id=sample_account_id, legal_entity_id=sample_legal_entity_id)
        d = req.to_dict()
        assert d["account_id"] == str(sample_account_id)
        assert d["legal_entity_id"] == str(sample_legal_entity_id)


# -------------------- Tests for GetAccountByCodeRequest --------------------
class TestGetAccountByCodeRequest:
    def test_construction(self, sample_legal_entity_id):
        req = GetAccountByCodeRequest(legal_entity_id=sample_legal_entity_id, account_code="1000")
        assert req.legal_entity_id == sample_legal_entity_id
        assert req.account_code == "1000"

    def test_to_dict(self, sample_legal_entity_id):
        req = GetAccountByCodeRequest(legal_entity_id=sample_legal_entity_id, account_code="1000")
        d = req.to_dict()
        assert d["legal_entity_id"] == str(sample_legal_entity_id)
        assert d["account_code"] == "1000"


# -------------------- Tests for GetAccountsQuery --------------------
class TestGetAccountsQuery:
    def test_construction_valid(self, sample_legal_entity_id):
        query = GetAccountsQuery(legal_entity_id=sample_legal_entity_id)
        assert query.page == 1
        assert query.page_size == 20
        assert query.include_children is True
        assert query.include_headers is True

    def test_validation_page_less_than_1(self, sample_legal_entity_id):
        with pytest.raises(ValueError, match="page must be >= 1"):
            GetAccountsQuery(legal_entity_id=sample_legal_entity_id, page=0)

    def test_validation_page_size_out_of_range(self, sample_legal_entity_id):
        with pytest.raises(ValueError, match="page_size must be between 1 and 500"):
            GetAccountsQuery(legal_entity_id=sample_legal_entity_id, page_size=0)
        with pytest.raises(ValueError, match="page_size must be between 1 and 500"):
            GetAccountsQuery(legal_entity_id=sample_legal_entity_id, page_size=501)

    def test_validation_account_type_invalid(self, sample_legal_entity_id):
        with pytest.raises(ValueError, match="Invalid account_type"):
            GetAccountsQuery(legal_entity_id=sample_legal_entity_id, account_type="INVALID")

    def test_get_offset(self, sample_legal_entity_id):
        query = GetAccountsQuery(legal_entity_id=sample_legal_entity_id, page=3, page_size=25)
        assert query.get_offset() == 50

    def test_to_dict(self, sample_legal_entity_id, sample_parent_id):
        query = GetAccountsQuery(
            legal_entity_id=sample_legal_entity_id,
            account_type="ASSET",
            is_active=True,
            parent_account_id=sample_parent_id,
            search="cash",
            include_children=False,
            include_headers=False,
            page=2,
            page_size=10,
        )
        d = query.to_dict()
        assert d["legal_entity_id"] == str(sample_legal_entity_id)
        assert d["account_type"] == "ASSET"
        assert d["is_active"] is True
        assert d["parent_account_id"] == str(sample_parent_id)
        assert d["search"] == "cash"
        assert d["include_children"] is False
        assert d["include_headers"] is False
        assert d["page"] == 2
        assert d["page_size"] == 10
        assert d["offset"] == 10


# -------------------- Tests for AccountResponse --------------------
class TestAccountResponse:
    def test_construction_valid(self, sample_account_response):
        assert sample_account_response.id is not None
        assert sample_account_response.account_code == "1000"
        assert sample_account_response.version == 1
        assert sample_account_response.created_at.tzinfo == UTC
        assert sample_account_response.updated_at.tzinfo == UTC

    def test_is_debit_balance(self, sample_account_response):
        assert sample_account_response.is_debit_balance() is True
        # Change normal_balance to credit
        sample_account_response.normal_balance = "credit"
        assert sample_account_response.is_debit_balance() is False

    def test_is_credit_balance(self, sample_account_response):
        assert sample_account_response.is_credit_balance() is False
        sample_account_response.normal_balance = "credit"
        assert sample_account_response.is_credit_balance() is True

    def test_to_dict(self, sample_account_response):
        d = sample_account_response.to_dict()
        assert d["id"] == str(sample_account_response.id)
        assert d["account_code"] == "1000"
        assert d["name"] == "Cash"
        assert d["account_type"] == "ASSET"
        assert d["normal_balance"] == "debit"
        assert d["opening_balance"] == "1000000"
        assert d["current_balance"] == "1500000"
        assert d["status"] == "ACTIVE"
        assert d["version"] == 1


# -------------------- Tests for AccountHierarchyNodeDTO --------------------
class TestAccountHierarchyNodeDTO:
    def test_construction_valid(self, sample_hierarchy_node):
        assert sample_hierarchy_node.account_code == "1000"
        assert sample_hierarchy_node.children == []

    def test_total_balance(self, sample_hierarchy_node):
        # Leaf node
        assert sample_hierarchy_node.total_balance() == Decimal("1500000")
        # With children
        child = AccountHierarchyNodeDTO(
            id=uuid4(),
            account_code="1010",
            name="Petty Cash",
            account_type="ASSET",
            normal_balance="debit",
            level=2,
            children=[],
            current_balance=Decimal("500000"),
        )
        sample_hierarchy_node.children.append(child)
        assert sample_hierarchy_node.total_balance() == Decimal("2000000")

    def test_flatten(self, sample_hierarchy_node):
        child1 = AccountHierarchyNodeDTO(
            id=uuid4(),
            account_code="1010",
            name="Child1",
            account_type="ASSET",
            normal_balance="debit",
            level=2,
            children=[],
        )
        child2 = AccountHierarchyNodeDTO(
            id=uuid4(),
            account_code="1020",
            name="Child2",
            account_type="ASSET",
            normal_balance="debit",
            level=2,
            children=[],
        )
        grandchild = AccountHierarchyNodeDTO(
            id=uuid4(),
            account_code="1011",
            name="Grandchild",
            account_type="ASSET",
            normal_balance="debit",
            level=3,
            children=[],
        )
        child1.children.append(grandchild)
        sample_hierarchy_node.children.extend([child1, child2])
        flat = sample_hierarchy_node.flatten()
        assert len(flat) == 4
        assert flat[0] is sample_hierarchy_node
        assert flat[1] is child1
        assert flat[2] is grandchild
        assert flat[3] is child2

    def test_find_child_by_code(self, sample_hierarchy_node):
        child = AccountHierarchyNodeDTO(
            id=uuid4(),
            account_code="1010",
            name="Child",
            account_type="ASSET",
            normal_balance="debit",
            level=2,
            children=[],
        )
        sample_hierarchy_node.children.append(child)
        found = sample_hierarchy_node.find_child_by_code("1010")
        assert found is child
        assert sample_hierarchy_node.find_child_by_code("9999") is None
        # Search in self
        assert sample_hierarchy_node.find_child_by_code("1000") is sample_hierarchy_node

    def test_find_child_by_id(self, sample_hierarchy_node):
        child_id = uuid4()
        child = AccountHierarchyNodeDTO(
            id=child_id,
            account_code="1010",
            name="Child",
            account_type="ASSET",
            normal_balance="debit",
            level=2,
            children=[],
        )
        sample_hierarchy_node.children.append(child)
        found = sample_hierarchy_node.find_child_by_id(child_id)
        assert found is child
        assert sample_hierarchy_node.find_child_by_id(uuid4()) is None
        # Search in self
        assert sample_hierarchy_node.find_child_by_id(sample_hierarchy_node.id) is sample_hierarchy_node

    def test_to_dict(self, sample_hierarchy_node):
        d = sample_hierarchy_node.to_dict()
        assert d["id"] == str(sample_hierarchy_node.id)
        assert d["account_code"] == "1000"
        assert d["name"] == "Cash"
        assert d["account_type"] == "ASSET"
        assert d["normal_balance"] == "debit"
        assert d["level"] == 1
        assert d["children"] == []
        assert d["is_header"] is False
        assert d["status"] == "ACTIVE"
        assert d["opening_balance"] == "1000000"
        assert d["current_balance"] == "1500000"


# -------------------- Tests for AccountBalanceResponse --------------------
class TestAccountBalanceResponse:
    def test_construction_valid(self, sample_balance_response):
        assert sample_balance_response.account_id is not None
        assert sample_balance_response.account_code == "1000"
        assert sample_balance_response.period_start.tzinfo == UTC
        assert sample_balance_response.period_end.tzinfo == UTC

    def test_to_dict(self, sample_balance_response):
        d = sample_balance_response.to_dict()
        assert d["account_id"] == str(sample_balance_response.account_id)
        assert d["account_code"] == "1000"
        assert d["account_name"] == "Cash"
        assert d["opening_balance"] == "1000000"
        assert d["period_debit"] == "500000"
        assert d["period_credit"] == "200000"
        assert d["ending_balance"] == "1300000"
        assert d["normal_balance"] == "debit"
        assert "period_start" in d
        assert "period_end" in d

    def test_is_debit_balance(self, sample_balance_response):
        # normal_balance is debit, ending_balance positive => debit balance
        assert sample_balance_response.is_debit_balance() is True
        # If ending_balance negative but normal balance debit, still considered debit? The logic: if normal_balance == "debit", return ending_balance > 0.
        sample_balance_response.ending_balance = Decimal("-500000")
        assert sample_balance_response.is_debit_balance() is False
        # If normal_balance == "credit", and ending_balance > 0, is_debit_balance returns False.
        sample_balance_response.normal_balance = "credit"
        sample_balance_response.ending_balance = Decimal("500000")
        assert sample_balance_response.is_debit_balance() is False
        # If normal_balance == "credit" and ending_balance < 0, returns True
        sample_balance_response.ending_balance = Decimal("-500000")
        assert sample_balance_response.is_debit_balance() is True

    def test_get_absolute_balance(self, sample_balance_response):
        assert sample_balance_response.get_absolute_balance() == Decimal("1300000")
        sample_balance_response.ending_balance = Decimal("-700000")
        assert sample_balance_response.get_absolute_balance() == Decimal("700000")


# -------------------- Tests for BulkImportResultDTO --------------------
class TestBulkImportResultDTO:
    def test_construction_valid(self):
        result = BulkImportResultDTO(
            total_rows=10,
            success_count=0,
            failure_count=0,
            failures=[],
            created_accounts=[],
            warnings=[],
        )
        assert result.total_rows == 10
        assert result.started_at.tzinfo == UTC

    def test_get_success_rate(self):
        result = BulkImportResultDTO(
            total_rows=10,
            success_count=8,
            failure_count=2,
            failures=[],
            created_accounts=[],
        )
        assert result.get_success_rate() == 80.0
        # zero total
        result.total_rows = 0
        assert result.get_success_rate() == 100.0

    def test_complete(self):
        result = BulkImportResultDTO(total_rows=1, success_count=0, failure_count=0, failures=[], created_accounts=[])
        assert result.completed_at is None
        result.complete()
        assert result.completed_at is not None
        assert result.completed_at.tzinfo == UTC

    def test_add_failure(self):
        result = BulkImportResultDTO(total_rows=1, success_count=0, failure_count=0, failures=[], created_accounts=[])
        result.add_failure(1, "Invalid account type")
        assert result.failure_count == 1
        assert len(result.failures) == 1
        assert result.failures[0]["row"] == 1
        assert result.failures[0]["error"] == "Invalid account type"

    def test_add_success(self, sample_account_response):
        result = BulkImportResultDTO(total_rows=1, success_count=0, failure_count=0, failures=[], created_accounts=[])
        result.add_success(sample_account_response)
        assert result.success_count == 1
        assert len(result.created_accounts) == 1
        assert result.created_accounts[0] == sample_account_response

    def test_to_dict(self, sample_account_response):
        result = BulkImportResultDTO(
            total_rows=2,
            success_count=1,
            failure_count=1,
            failures=[{"row": 1, "error": "Error"}],
            created_accounts=[sample_account_response],
            warnings=["Warning 1"],
            started_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
            completed_at=datetime(2025, 1, 1, 0, 0, 10, tzinfo=UTC),
        )
        d = result.to_dict()
        assert d["total_rows"] == 2
        assert d["success_count"] == 1
        assert d["failure_count"] == 1
        assert len(d["failures"]) == 1
        assert len(d["created_accounts"]) == 1
        assert d["warnings"] == ["Warning 1"]
        assert d["started_at"] == "2025-01-01T00:00:00+00:00"
        assert d["completed_at"] == "2025-01-01T00:00:10+00:00"
        assert d["success_rate"] == 50.0


# -------------------- Tests for AccountValidationResult --------------------
class TestAccountValidationResult:
    def test_construction_valid(self):
        result = AccountValidationResult(is_valid=True)
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_to_dict(self):
        result = AccountValidationResult(is_valid=False, errors=["error1"], warnings=["warning1"])
        d = result.to_dict()
        assert d["is_valid"] is False
        assert d["errors"] == ["error1"]
        assert d["warnings"] == ["warning1"]

    def test_add_error(self):
        result = AccountValidationResult(is_valid=True)
        result.add_error("Something wrong")
        assert result.is_valid is False
        assert result.errors == ["Something wrong"]

    def test_add_warning(self):
        result = AccountValidationResult(is_valid=True)
        result.add_warning("Something to note")
        assert result.is_valid is True
        assert result.warnings == ["Something to note"]


# -------------------- Tests for AccountDTOFactory --------------------
class TestAccountDTOFactory:
    def test_create_account_response(self, sample_account_id, sample_legal_entity_id):
        response = AccountDTOFactory.create_account_response(
            account_id=sample_account_id,
            legal_entity_id=sample_legal_entity_id,
            account_code="2000",
            name="Accounts Payable",
            account_type="LIABILITY",
            normal_balance="credit",
            parent_account_id=None,
            level=1,
            created_by=uuid4(),
            description="AP account",
            opening_balance=Decimal("500000"),
            currency_code="IDR",
            is_header=False,
            status="ACTIVE",
            tax_code="PPN",
            financial_report_section="Current Liabilities",
        )
        assert response.id == sample_account_id
        assert response.account_code == "2000"
        assert response.name == "Accounts Payable"
        assert response.account_type == "LIABILITY"
        assert response.normal_balance == "credit"
        assert response.opening_balance == Decimal("500000")
        assert response.is_header is False
        assert response.status == "ACTIVE"
        assert response.created_at is not None
        assert response.created_at.tzinfo == UTC
        assert response.version == 1

    def test_create_hierarchy_node(self):
        child = AccountHierarchyNodeDTO(
            id=uuid4(),
            account_code="2010",
            name="Child AP",
            account_type="LIABILITY",
            normal_balance="credit",
            level=2,
            children=[],
        )
        node = AccountDTOFactory.create_hierarchy_node(
            account_code="2000",
            name="AP",
            account_type="LIABILITY",
            normal_balance="credit",
            level=1,
            is_header=True,
            account_id=uuid4(),
            status="ACTIVE",
            opening_balance=Decimal("500000"),
            current_balance=Decimal("600000"),
            description="AP header",
            children=[child],
        )
        assert node.account_code == "2000"
        assert node.is_header is True
        assert len(node.children) == 1
        assert node.children[0] is child

    def test_create_balance_response(self, sample_account_id):
        period_start = datetime.now(UTC) - timedelta(days=30)
        period_end = datetime.now(UTC)
        response = AccountDTOFactory.create_balance_response(
            account_id=sample_account_id,
            account_code="1000",
            account_name="Cash",
            opening_balance=Decimal("1000000"),
            period_debit=Decimal("500000"),
            period_credit=Decimal("200000"),
            ending_balance=Decimal("1300000"),
            normal_balance="debit",
            period_start=period_start,
            period_end=period_end,
            currency_code="IDR",
        )
        assert response.account_id == sample_account_id
        assert response.account_code == "1000"
        assert response.opening_balance == Decimal("1000000")
        assert response.period_debit == Decimal("500000")
        assert response.period_credit == Decimal("200000")
        assert response.ending_balance == Decimal("1300000")
        assert response.period_start == period_start
        assert response.period_end == period_end
        assert response.currency_code == "IDR"
