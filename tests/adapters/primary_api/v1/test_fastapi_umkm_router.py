# adapters/primary_api/v1/test_fastapi_umkm_router.py
"""
Comprehensive unit tests for FastAPI UMKM Simplified Router.

Covers:
- IdempotencyManager
- All enum classes
- All request/response schemas (valid & invalid cases)
- All endpoint functions (with mocked service layer)
- Account code validation against SIMPLIFIED_ACCOUNTS
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from adapters.primary_api.v1.fastapi_umkm_router import (
    SIMPLIFIED_ACCOUNTS,
    BalanceSheetSimpleSchema,
    BusinessProfileResponseSchema,
    BusinessProfileSchema,
    CashFlowSimpleSchema,
    IdempotencyManager,
    IncomeStatementSimpleSchema,
    SimplifiedJournalEntrySchema,
    SimplifiedJournalResponseSchema,
    TaxComplianceHelperResponseSchema,
    TransactionCategory,
    TransactionSummarySchema,
    UMKMJournalStatus,
    cancel_journal_entry,
    create_journal_entry,
    export_transactions,
    get_balance_sheet,
    get_business_profile,
    get_cash_flow,
    get_income_statement,
    get_journal_entry,
    get_journal_history,
    get_journal_status,
    get_simplified_accounts,
    get_tax_compliance,
    get_transaction_summary,
    get_umkm_service,
    list_journal_entries,
    post_journal_entry,
    reverse_journal_entry,
    update_business_profile,
    update_journal_entry,
)

# =============================================================================
# Helper fixtures
# =============================================================================

@pytest.fixture
def mock_token_payload():
    return MagicMock(user_id=uuid4())


@pytest.fixture
def mock_legal_entity_id():
    return uuid4()


@pytest.fixture
def mock_umkm_service():
    svc = AsyncMock()

    # Journal response
    def create_mock_journal(**kwargs):
        defaults = {
            "id": uuid4(),
            "journal_number": "JRN-2025-001",
            "journal_date": date.today(),
            "description": "Test entry",
            "debit_account_code": "1-1100",
            "credit_account_code": "4-4100",
            "amount": Decimal("1000000"),
            "category": "revenue",
            "status": "draft",
            "tax_id": None,
            "attachment_url": None,
            "notes": "Test notes",
            "posted_at": None,
            "posted_by": None,
            "created_at": datetime.now(UTC),
            "created_by": uuid4(),
            "created_by_name": "Admin",
            "version": 1,
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.create_journal_entry.return_value = create_mock_journal()
    svc.get_journal_entry.return_value = create_mock_journal()
    svc.list_journal_entries.return_value = MagicMock(
        items=[create_mock_journal()],
        total=1,
    )
    svc.update_journal_entry.return_value = create_mock_journal()
    svc.cancel_journal_entry.return_value = create_mock_journal(status="cancelled")
    svc.post_journal_entry.return_value = create_mock_journal(status="posted")
    svc.reverse_journal_entry.return_value = create_mock_journal(status="reversed")

    # Reports
    svc.get_income_statement.return_value = MagicMock(
        period_name="Jan 2025",
        total_revenue=Decimal("10000000"),
        total_cogs=Decimal("4000000"),
        gross_profit=Decimal("6000000"),
        total_expenses=Decimal("3000000"),
        operating_profit=Decimal("3000000"),
        other_income=Decimal("500000"),
        other_expenses=Decimal("200000"),
        net_income=Decimal("3300000"),
        revenue_details=[{"account": "4-4100", "amount": 8000000}],
        expense_details=[{"account": "5-5200", "amount": 3000000}],
    )
    svc.get_balance_sheet.return_value = MagicMock(
        total_assets=Decimal("50000000"),
        total_liabilities=Decimal("20000000"),
        total_equity=Decimal("30000000"),
        assets_details=[{"account": "1-1100", "amount": 10000000}],
        liabilities_details=[{"account": "2-2100", "amount": 20000000}],
        equity_details=[{"account": "3-3100", "amount": 30000000}],
        is_balanced=True,
    )
    svc.get_cash_flow.return_value = MagicMock(
        beginning_cash=Decimal("5000000"),
        cash_in_from_operations=Decimal("8000000"),
        cash_out_from_operations=Decimal("3000000"),
        net_cash_operations=Decimal("5000000"),
        cash_in_from_investing=Decimal("0"),
        cash_out_from_investing=Decimal("1000000"),
        net_cash_investing=Decimal("-1000000"),
        cash_in_from_financing=Decimal("0"),
        cash_out_from_financing=Decimal("0"),
        net_cash_financing=Decimal("0"),
        net_cash_flow=Decimal("4000000"),
        ending_cash=Decimal("9000000"),
    )
    svc.get_tax_compliance.return_value = MagicMock(
        total_revenue_period=Decimal("5000000"),
        total_revenue_ytd=Decimal("20000000"),
        estimated_pph_final=Decimal("25000"),
        tax_due_reminder="PPh Final 0.5% due",
        submission_deadline=date(2025, 2, 15),
        is_required_to_file=True,
        notes="Based on monthly revenue",
    )
    svc.get_business_profile.return_value = MagicMock(
        id=uuid4(),
        legal_entity_id=uuid4(),
        business_name="UMKM A",
        business_type="Trading",
        npwp="123456789012345",
        business_address="Jl. Raya No. 1",
        phone="08123456789",
        email="umkm@example.com",
        website="umkm.example.com",
        established_date=date(2020, 1, 1),
        industry="Retail",
        uses_final_tax=True,
        accounting_method="cash",
        fiscal_year_start=1,
        tax_submission_reminder_days=7,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        version=1,
    )
    svc.update_business_profile.return_value = svc.get_business_profile.return_value

    # Summary
    svc.get_transaction_summary.return_value = MagicMock(
        by_category={"revenue": 10000000, "operating_expense": 3000000},
        by_account={"1-1100": 5000000, "4-4100": 8000000},
        by_month={"2025-01": 5000000},
        total_transactions=10,
        total_amount=Decimal("15000000"),
    )

    # History & status
    svc.get_journal_history.return_value = [
        MagicMock(
            timestamp=datetime.now(UTC),
            action="create",
            from_status=None,
            to_status="draft",
            actor_id=uuid4(),
            actor_name="Admin",
            reason="Initial",
            notes="Created",
        )
    ]
    svc.get_journal_status.return_value = MagicMock(
        journal_number="JRN-2025-001",
        status="draft",
        status_description="Draft entry",
        can_post=True,
        can_reverse=False,
        can_cancel=True,
        is_locked=False,
        is_archived=False,
        posted_at=None,
        posted_by=None,
    )

    # Export
    svc.export_transactions.return_value = b"csv data"

    return svc


# =============================================================================
# Tests for IdempotencyManager
# =============================================================================

class TestIdempotencyManager:
    def test_initialization(self):
        manager = IdempotencyManager()
        assert manager._storage == {}
        assert manager._ttl_seconds == 86400

    def test_get_cached_result_miss(self):
        manager = IdempotencyManager()
        result = manager.get_cached_result("key1", "method1")
        assert result is None

    def test_cache_and_retrieve(self):
        manager = IdempotencyManager()
        data = {"id": "123", "status": "ok"}
        manager.cache_result("key1", "method1", data)
        cached = manager.get_cached_result("key1", "method1")
        assert cached == data

    def test_cache_serializes_complex_types(self):
        manager = IdempotencyManager()
        data = {"date": date.today(), "decimal": Decimal("10.50")}
        manager.cache_result("key2", "method2", data)
        cached = manager.get_cached_result("key2", "method2")
        assert cached is not None
        assert "date" in cached

    def test_cache_expiration(self):
        manager = IdempotencyManager()
        manager._ttl_seconds = 0
        manager.cache_result("key3", "method3", {"foo": "bar"})
        cached = manager.get_cached_result("key3", "method3")
        assert cached is None

    def test_key_generation_deterministic(self):
        manager = IdempotencyManager()
        key1 = manager._get_key("abc", "create_journal")
        key2 = manager._get_key("abc", "create_journal")
        key3 = manager._get_key("abc", "update_journal")
        assert key1 == key2
        assert key1 != key3


# =============================================================================
# Tests for Enums
# =============================================================================

class TestEnums:
    def test_umkm_journal_status_values(self):
        assert UMKMJournalStatus.DRAFT.value == "draft"
        assert UMKMJournalStatus.POSTED.value == "posted"
        assert UMKMJournalStatus.CANCELLED.value == "cancelled"
        assert UMKMJournalStatus.REVERSED.value == "reversed"

    def test_transaction_category_values(self):
        assert TransactionCategory.REVENUE.value == "revenue"
        assert TransactionCategory.COST_OF_GOODS_SOLD.value == "cogs"
        assert TransactionCategory.OPERATING_EXPENSE.value == "operating_expense"
        assert TransactionCategory.OTHER_INCOME.value == "other_income"
        assert TransactionCategory.OTHER_EXPENSE.value == "other_expense"
        assert TransactionCategory.ASSET.value == "asset"
        assert TransactionCategory.LIABILITY.value == "liability"
        assert TransactionCategory.EQUITY.value == "equity"


# =============================================================================
# Tests for Schemas (validation)
# =============================================================================

class TestSimplifiedJournalEntrySchema:
    def test_valid_schema(self):
        data = {
            "journal_date": date.today(),
            "description": "Penjualan tunai",
            "debit_account_code": "1-1100",
            "credit_account_code": "4-4100",
            "amount": Decimal("1000000"),
            "category": TransactionCategory.REVENUE,
            "notes": "Test",
        }
        schema = SimplifiedJournalEntrySchema(**data)
        assert schema.description == "Penjualan tunai"
        assert schema.amount == Decimal("1000000")

    def test_invalid_debit_account_code(self):
        with pytest.raises(ValueError, match="Invalid account code"):
            SimplifiedJournalEntrySchema(
                description="Test",
                debit_account_code="INVALID",
                credit_account_code="1-1100",
                amount=Decimal("1000"),
            )

    def test_invalid_credit_account_code(self):
        with pytest.raises(ValueError, match="Invalid account code"):
            SimplifiedJournalEntrySchema(
                description="Test",
                debit_account_code="1-1100",
                credit_account_code="INVALID",
                amount=Decimal("1000"),
            )

    def test_same_debit_credit_accounts(self):
        with pytest.raises(ValueError, match="Debit and credit accounts must be different"):
            SimplifiedJournalEntrySchema(
                description="Test",
                debit_account_code="1-1100",
                credit_account_code="1-1100",
                amount=Decimal("1000"),
            )

    def test_amount_positive(self):
        with pytest.raises(ValueError):
            SimplifiedJournalEntrySchema(
                description="Test",
                debit_account_code="1-1100",
                credit_account_code="4-4100",
                amount=Decimal("0"),
            )

    def test_description_min_length(self):
        with pytest.raises(ValueError):
            SimplifiedJournalEntrySchema(
                description="ab",  # too short
                debit_account_code="1-1100",
                credit_account_code="4-4100",
                amount=Decimal("1000"),
            )


class TestBusinessProfileSchema:
    def test_valid_schema(self):
        data = {
            "business_name": "UMKM A",
            "business_type": "Trading",
            "npwp": "123456789012345",
            "business_address": "Jl. Raya No. 1",
            "phone": "08123456789",
            "email": "umkm@example.com",
            "website": "umkm.example.com",
            "established_date": date(2020, 1, 1),
            "industry": "Retail",
            "uses_final_tax": True,
            "accounting_method": "cash",
            "fiscal_year_start": 1,
            "tax_submission_reminder_days": 7,
        }
        schema = BusinessProfileSchema(**data)
        assert schema.business_name == "UMKM A"
        assert schema.npwp == "123456789012345"

    def test_npwp_min_length(self):
        with pytest.raises(ValueError):
            BusinessProfileSchema(
                business_name="Test",
                business_type="Test",
                npwp="123",  # too short
            )

    def test_fiscal_year_start_range(self):
        # valid
        schema = BusinessProfileSchema(
            business_name="Test",
            business_type="Test",
            fiscal_year_start=12,
        )
        assert schema.fiscal_year_start == 12
        # invalid >12
        with pytest.raises(ValueError):
            BusinessProfileSchema(
                business_name="Test",
                business_type="Test",
                fiscal_year_start=13,
            )


# =============================================================================
# Tests for Endpoint Functions (with mocks)
# =============================================================================

@pytest.mark.asyncio
class TestJournalCRUD:
    async def test_create_success(self, mock_umkm_service, mock_token_payload, mock_legal_entity_id):
        request = SimplifiedJournalEntrySchema(
            description="Penjualan tunai",
            debit_account_code="1-1100",
            credit_account_code="4-4100",
            amount=Decimal("1000000"),
            category=TransactionCategory.REVENUE,
        )
        result = await create_journal_entry(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_umkm_service,
        )
        assert isinstance(result, SimplifiedJournalResponseSchema)
        assert result.description == "Test entry"
        assert result.status == UMKMJournalStatus.DRAFT
        mock_umkm_service.create_journal_entry.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            journal_date=request.journal_date,
            description=request.description,
            debit_account_code=request.debit_account_code,
            credit_account_code=request.credit_account_code,
            amount=request.amount,
            category="revenue",
            tax_id=None,
            attachment_url=None,
            notes=None,
            created_by=mock_token_payload.user_id,
        )

    async def test_create_idempotency(self, mock_umkm_service, mock_token_payload, mock_legal_entity_id):
        request = SimplifiedJournalEntrySchema(
            description="Test",
            debit_account_code="1-1100",
            credit_account_code="4-4100",
            amount=Decimal("1000"),
        )
        with patch("adapters.primary_api.v1.fastapi_umkm_router._idempotency_manager") as mock_im:
            mock_im.get_cached_result.return_value = {
                "id": str(uuid4()),
                "journal_number": "JRN-001",
                "journal_date": date.today().isoformat(),
                "description": "Test",
                "debit_account_code": "1-1100",
                "debit_account_name": "Kas",
                "credit_account_code": "4-4100",
                "credit_account_name": "Pendapatan Usaha",
                "amount": "1000.00",
                "category": None,
                "status": "draft",
                "tax_id": None,
                "attachment_url": None,
                "notes": None,
                "posted_at": None,
                "posted_by": None,
                "created_at": datetime.now(UTC).isoformat(),
                "created_by": str(uuid4()),
                "created_by_name": None,
                "version": 1,
            }
            result = await create_journal_entry(
                request=request,
                idempotency_key="abc123",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_umkm_service,
            )
            assert isinstance(result, SimplifiedJournalResponseSchema)
            mock_umkm_service.create_journal_entry.assert_not_called()

    async def test_create_value_error(self, mock_umkm_service, mock_token_payload, mock_legal_entity_id):
        mock_umkm_service.create_journal_entry.side_effect = ValueError("Invalid account")
        request = SimplifiedJournalEntrySchema(
            description="Test",
            debit_account_code="1-1100",
            credit_account_code="4-4100",
            amount=Decimal("1000"),
        )
        with pytest.raises(HTTPException) as exc:
            await create_journal_entry(
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_umkm_service,
            )
        assert exc.value.status_code == 422

    async def test_list_journals(self, mock_umkm_service, mock_legal_entity_id):
        result = await list_journal_entries(
            start_date=None,
            end_date=None,
            status=UMKMJournalStatus.DRAFT,
            category=TransactionCategory.REVENUE,
            page=1,
            page_size=20,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_umkm_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], SimplifiedJournalResponseSchema)
        mock_umkm_service.list_journal_entries.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            start_date=None,
            end_date=None,
            status="draft",
            category="revenue",
            page=1,
            page_size=20,
        )

    async def test_get_journal_success(self, mock_umkm_service, mock_legal_entity_id):
        journal_id = uuid4()
        result = await get_journal_entry(
            journal_id=journal_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_umkm_service,
        )
        assert isinstance(result, SimplifiedJournalResponseSchema)
        mock_umkm_service.get_journal_entry.assert_called_once_with(journal_id, mock_legal_entity_id)

    async def test_get_journal_not_found(self, mock_umkm_service, mock_legal_entity_id):
        mock_umkm_service.get_journal_entry.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_journal_entry(
                journal_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                service=mock_umkm_service,
            )
        assert exc.value.status_code == 404

    async def test_update_journal_success(self, mock_umkm_service, mock_token_payload, mock_legal_entity_id):
        journal_id = uuid4()
        request = SimplifiedJournalEntrySchema(
            description="Updated",
            debit_account_code="1-1100",
            credit_account_code="4-4100",
            amount=Decimal("2000"),
        )
        result = await update_journal_entry(
            journal_id=journal_id,
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_umkm_service,
        )
        assert isinstance(result, SimplifiedJournalResponseSchema)
        mock_umkm_service.update_journal_entry.assert_called_once()

    async def test_update_journal_not_found(self, mock_umkm_service, mock_token_payload, mock_legal_entity_id):
        mock_umkm_service.update_journal_entry.return_value = None
        request = SimplifiedJournalEntrySchema(
            description="Test",
            debit_account_code="1-1100",
            credit_account_code="4-4100",
            amount=Decimal("1000"),
        )
        with pytest.raises(HTTPException) as exc:
            await update_journal_entry(
                journal_id=uuid4(),
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_umkm_service,
            )
        assert exc.value.status_code == 404

    async def test_cancel_journal_success(self, mock_umkm_service, mock_token_payload, mock_legal_entity_id):
        journal_id = uuid4()
        result = await cancel_journal_entry(
            journal_id=journal_id,
            reason="Mistake",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_umkm_service,
        )
        assert result["status"] == "cancelled"
        mock_umkm_service.cancel_journal_entry.assert_called_once_with(
            journal_id, mock_token_payload.user_id, mock_legal_entity_id, "Mistake"
        )

    async def test_cancel_journal_not_found(self, mock_umkm_service, mock_token_payload, mock_legal_entity_id):
        mock_umkm_service.cancel_journal_entry.return_value = None
        with pytest.raises(HTTPException) as exc:
            await cancel_journal_entry(
                journal_id=uuid4(),
                reason="",
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_umkm_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestJournalPostAndReverse:
    async def test_post_success(self, mock_umkm_service, mock_token_payload, mock_legal_entity_id):
        journal_id = uuid4()
        result = await post_journal_entry(
            journal_id=journal_id,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_umkm_service,
        )
        assert isinstance(result, SimplifiedJournalResponseSchema)
        assert result.status == UMKMJournalStatus.POSTED
        mock_umkm_service.post_journal_entry.assert_called_once_with(
            journal_id, mock_token_payload.user_id, mock_legal_entity_id
        )

    async def test_post_not_found(self, mock_umkm_service, mock_token_payload, mock_legal_entity_id):
        mock_umkm_service.post_journal_entry.return_value = None
        with pytest.raises(HTTPException) as exc:
            await post_journal_entry(
                journal_id=uuid4(),
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_umkm_service,
            )
        assert exc.value.status_code == 404

    async def test_reverse_success(self, mock_umkm_service, mock_token_payload, mock_legal_entity_id):
        journal_id = uuid4()
        result = await reverse_journal_entry(
            journal_id=journal_id,
            reason="Correction",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_umkm_service,
        )
        assert isinstance(result, SimplifiedJournalResponseSchema)
        assert result.status == UMKMJournalStatus.REVERSED
        mock_umkm_service.reverse_journal_entry.assert_called_once_with(
            journal_id=journal_id,
            reason="Correction",
            reversed_by=mock_token_payload.user_id,
            legal_entity_id=mock_legal_entity_id,
        )

    async def test_reverse_not_found(self, mock_umkm_service, mock_token_payload, mock_legal_entity_id):
        mock_umkm_service.reverse_journal_entry.return_value = None
        with pytest.raises(HTTPException) as exc:
            await reverse_journal_entry(
                journal_id=uuid4(),
                reason="Test",
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_umkm_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestFinancialReports:
    async def test_get_income_statement(self, mock_umkm_service, mock_legal_entity_id):
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        result = await get_income_statement(
            period_start=start,
            period_end=end,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_umkm_service,
        )
        assert isinstance(result, IncomeStatementSimpleSchema)
        assert result.total_revenue == Decimal("10000000")
        assert result.net_income == Decimal("3300000")
        mock_umkm_service.get_income_statement.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            period_start=start,
            period_end=end,
        )

    async def test_get_balance_sheet(self, mock_umkm_service, mock_legal_entity_id):
        as_of = date.today()
        result = await get_balance_sheet(
            as_of_date=as_of,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_umkm_service,
        )
        assert isinstance(result, BalanceSheetSimpleSchema)
        assert result.total_assets == Decimal("50000000")
        assert result.is_balanced is True
        mock_umkm_service.get_balance_sheet.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            as_of_date=as_of,
        )

    async def test_get_cash_flow(self, mock_umkm_service, mock_legal_entity_id):
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        result = await get_cash_flow(
            period_start=start,
            period_end=end,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_umkm_service,
        )
        assert isinstance(result, CashFlowSimpleSchema)
        assert result.beginning_cash == Decimal("5000000")
        assert result.ending_cash == Decimal("9000000")
        mock_umkm_service.get_cash_flow.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            period_start=start,
            period_end=end,
        )


@pytest.mark.asyncio
class TestTaxCompliance:
    async def test_get_tax_compliance(self, mock_umkm_service, mock_legal_entity_id):
        result = await get_tax_compliance(
            period_year=2025,
            period_month=1,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_umkm_service,
        )
        assert isinstance(result, TaxComplianceHelperResponseSchema)
        assert result.estimated_pph_final == Decimal("25000")
        assert result.is_required_to_file is True
        mock_umkm_service.get_tax_compliance.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            period_year=2025,
            period_month=1,
        )


@pytest.mark.asyncio
class TestBusinessProfile:
    async def test_get_profile_success(self, mock_umkm_service, mock_legal_entity_id):
        result = await get_business_profile(
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_umkm_service,
        )
        assert isinstance(result, BusinessProfileResponseSchema)
        assert result.business_name == "UMKM A"
        mock_umkm_service.get_business_profile.assert_called_once_with(mock_legal_entity_id)

    async def test_get_profile_not_found(self, mock_umkm_service, mock_legal_entity_id):
        mock_umkm_service.get_business_profile.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_business_profile(
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                service=mock_umkm_service,
            )
        assert exc.value.status_code == 404

    async def test_update_profile_success(self, mock_umkm_service, mock_token_payload, mock_legal_entity_id):
        request = BusinessProfileSchema(
            business_name="Updated Name",
            business_type="Service",
            npwp="123456789012345",
            fiscal_year_start=1,
            tax_submission_reminder_days=7,
        )
        result = await update_business_profile(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_umkm_service,
        )
        assert isinstance(result, BusinessProfileResponseSchema)
        mock_umkm_service.update_business_profile.assert_called_once()

    async def test_update_profile_not_found(self, mock_umkm_service, mock_token_payload, mock_legal_entity_id):
        mock_umkm_service.update_business_profile.return_value = None
        request = BusinessProfileSchema(
            business_name="Test",
            business_type="Test",
            fiscal_year_start=1,
            tax_submission_reminder_days=7,
        )
        with pytest.raises(HTTPException) as exc:
            await update_business_profile(
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_umkm_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestTransactionSummary:
    async def test_get_summary(self, mock_umkm_service, mock_legal_entity_id):
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        result = await get_transaction_summary(
            period_start=start,
            period_end=end,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_umkm_service,
        )
        assert isinstance(result, TransactionSummarySchema)
        assert result.total_amount == Decimal("15000000")
        assert result.total_transactions == 10
        mock_umkm_service.get_transaction_summary.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            period_start=start,
            period_end=end,
        )


@pytest.mark.asyncio
class TestChartOfAccounts:
    async def test_get_accounts_all(self):
        result = await get_simplified_accounts(
            account_type=None,
            _permission=None,
        )
        assert isinstance(result, list)
        assert len(result) == len(SIMPLIFIED_ACCOUNTS)
        # Check first item structure
        first = result[0]
        assert "account_code" in first
        assert "account_name" in first
        assert "account_type" in first
        assert "normal_balance" in first

    async def test_get_accounts_filtered(self):
        result = await get_simplified_accounts(
            account_type="ASSET",
            _permission=None,
        )
        assert isinstance(result, list)
        assert all(acc["account_type"] == "ASSET" for acc in result)


@pytest.mark.asyncio
class TestJournalHistoryAndStatus:
    async def test_get_journal_history(self, mock_umkm_service, mock_legal_entity_id):
        journal_id = uuid4()
        result = await get_journal_history(
            journal_id=journal_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_umkm_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["action"] == "create"
        mock_umkm_service.get_journal_history.assert_called_once_with(journal_id, mock_legal_entity_id)

    async def test_get_journal_status_success(self, mock_umkm_service, mock_legal_entity_id):
        journal_id = uuid4()
        result = await get_journal_status(
            journal_id=journal_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_umkm_service,
        )
        assert result["status"] == "draft"
        assert result["can_post"] is True
        mock_umkm_service.get_journal_status.assert_called_once_with(journal_id, mock_legal_entity_id)

    async def test_get_journal_status_not_found(self, mock_umkm_service, mock_legal_entity_id):
        mock_umkm_service.get_journal_status.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_journal_status(
                journal_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                service=mock_umkm_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestExport:
    async def test_export_csv(self, mock_umkm_service, mock_legal_entity_id):
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        response = await export_transactions(
            start_date=start,
            end_date=end,
            format="csv",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_umkm_service,
        )
        assert response.body == b"csv data"
        assert response.media_type == "text/csv"
        assert "attachment" in response.headers["Content-Disposition"]
        mock_umkm_service.export_transactions.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            start_date=start,
            end_date=end,
            format="csv",
        )

    async def test_export_excel(self, mock_umkm_service, mock_legal_entity_id):
        mock_umkm_service.export_transactions.return_value = b"excel data"
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        response = await export_transactions(
            start_date=start,
            end_date=end,
            format="excel",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_umkm_service,
        )
        assert response.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# =============================================================================
# Tests for Dependency Injection
# =============================================================================

@pytest.mark.asyncio
async def test_get_umkm_service():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve.return_value = "service"
    result = await get_umkm_service(request)
    assert result == "service"
