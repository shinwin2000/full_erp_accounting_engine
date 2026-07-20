# adapters/primary_api/v1/test_fastapi_consolidation_router.py
"""
Comprehensive unit tests for FastAPI Consolidation Router.

Covers:
- IdempotencyManager
- All enum classes
- All request/response schemas (valid & invalid cases)
- All endpoint functions (with mocked service layer)
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from adapters.primary_api.v1.fastapi_consolidation_router import (
    BalanceSheetConsolidatedSchema,
    ConsolidationGroupCreateSchema,
    ConsolidationGroupResponseSchema,
    ConsolidationGroupUpdateSchema,
    ConsolidationMemberResponseSchema,
    ConsolidationMemberSchema,
    ConsolidationMethod,
    ConsolidationRunRequestSchema,
    ConsolidationRunResponseSchema,
    ConsolidationStatus,
    CurrencyTranslationMethod,
    EliminationEntryCreateSchema,
    EliminationEntryResponseSchema,
    EliminationStatus,
    IdempotencyManager,
    IncomeStatementConsolidatedSchema,
    IntercompanyTransactionCreateSchema,
    IntercompanyTransactionResponseSchema,
    IntercompanyType,
    NCICalculationSchema,
    NCIResponseSchema,
    add_group_member,
    calculate_nci,
    create_consolidation_group,
    create_intercompany_transaction,
    deactivate_consolidation_group,
    export_consolidation_report,
    generate_elimination_entries,
    get_consolidated_balance_sheet,
    get_consolidated_income_statement,
    get_consolidation_group,
    get_consolidation_history,
    get_consolidation_report,
    get_consolidation_status,
    get_intercompany_transaction,
    list_consolidation_groups,
    list_elimination_entries,
    list_group_members,
    list_intercompany_transactions,
    post_elimination_entry,
    remove_group_member,
    reverse_consolidation,
    run_consolidation,
    update_consolidation_group,
    update_group_member,
)

# =============================================================================
# Helper fixtures
# =============================================================================

@pytest.fixture
def mock_token_payload():
    return MagicMock(user_id=uuid4())


@pytest.fixture
def mock_consolidation_service():
    svc = AsyncMock()

    # Group responses
    svc.create_group.return_value = MagicMock(
        id=uuid4(),
        group_code="GRP-001",
        group_name="Test Group",
        parent_entity_id=None,
        parent_entity_name=None,
        functional_currency="IDR",
        description="Test description",
        is_active=True,
        member_count=0,
        fiscal_year_start=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
        version=1,
    )
    svc.get_group_by_id.return_value = svc.create_group.return_value
    svc.list_groups.return_value = [svc.create_group.return_value]
    svc.update_group.return_value = svc.create_group.return_value
    svc.deactivate_group.return_value = MagicMock(
        group_code="GRP-001",
        is_active=False,
    )

    # Member responses
    svc.add_member.return_value = MagicMock(
        id=uuid4(),
        legal_entity_id=uuid4(),
        legal_entity_name="Entity A",
        legal_entity_code="ENT-001",
        ownership_percentage=Decimal("75.00"),
        consolidation_method="full",
        effective_date=date.today(),
        notes="Test member",
        is_active=True,
        joined_at=datetime.now(UTC),
        created_by=uuid4(),
        version=1,
    )
    svc.get_group_members.return_value = [svc.add_member.return_value]
    svc.update_member.return_value = svc.add_member.return_value
    svc.remove_member.return_value = MagicMock(
        legal_entity_id=uuid4(),
        legal_entity_name="Entity A",
    )

    # Intercompany transaction responses
    svc.create_intercompany_transaction.return_value = MagicMock(
        id=uuid4(),
        transaction_number="IC-2025-001",
        from_legal_entity_id=uuid4(),
        from_legal_entity_name="Entity A",
        to_legal_entity_id=uuid4(),
        to_legal_entity_name="Entity B",
        transaction_date=date.today(),
        amount=Decimal("1000.00"),
        amount_in_group_currency=Decimal("1000.00"),
        currency="IDR",
        exchange_rate=Decimal("1.0"),
        transaction_type="sales",
        description="Test transaction",
        reference_number="REF-123",
        invoice_number="INV-123",
        elimination_status="pending",
        elimination_entry_id=None,
        notes="Test notes",
        created_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
        version=1,
    )
    svc.get_intercompany_transaction_by_id.return_value = (
        svc.create_intercompany_transaction.return_value
    )
    svc.list_intercompany_transactions.return_value = [
        svc.create_intercompany_transaction.return_value
    ]

    # Elimination responses
    svc.generate_elimination_entries.return_value = MagicMock(
        id=uuid4(),
        elimination_number="ELIM-2025-001",
        consolidation_group_id=uuid4(),
        group_name="Test Group",
        fiscal_year=2025,
        period=1,
        description="Elimination entry",
        journal_id=uuid4(),
        status="pending",
        intercompany_transaction_ids=[uuid4()],
        eliminated_amount=Decimal("1000.00"),
        nci_adjustment=Decimal("0"),
        notes="Test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
        posted_at=None,
        posted_by=None,
        version=1,
    )
    svc.post_elimination_entry.return_value = svc.generate_elimination_entries.return_value
    svc.list_elimination_entries.return_value = [svc.generate_elimination_entries.return_value]

    # NCI responses
    svc.calculate_nci.return_value = [
        MagicMock(
            legal_entity_id=uuid4(),
            legal_entity_name="Entity A",
            ownership_percentage=Decimal("25.00"),
            nci_share_net_income=Decimal("50.00"),
            nci_share_oci=Decimal("0"),
            nci_share_dividends=Decimal("0"),
            beginning_nci_balance=Decimal("1000.00"),
            ending_nci_balance=Decimal("1050.00"),
            journal_id=uuid4(),
        )
    ]

    # Consolidation run responses
    svc.run_consolidation.return_value = MagicMock(
        id=uuid4(),
        consolidation_number="CON-2025-001",
        consolidation_group_id=uuid4(),
        group_name="Test Group",
        fiscal_year=2025,
        period=1,
        as_of_date=date.today(),
        reporting_currency="IDR",
        status="completed",
        total_assets=Decimal("50000"),
        total_liabilities=Decimal("20000"),
        total_equity=Decimal("30000"),
        total_revenue=Decimal("10000"),
        total_expense=Decimal("8000"),
        net_income=Decimal("2000"),
        nci_amount=Decimal("500"),
        equity_attributable_to_parent=Decimal("1500"),
        elimination_entries_count=3,
        intercompany_transactions_count=5,
        journal_ids=[uuid4()],
        created_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
        completed_at=datetime.now(UTC),
    )
    svc.list_consolidation_runs.return_value = [svc.run_consolidation.return_value]
    svc.get_consolidation_status.return_value = MagicMock(
        consolidation_number="CON-2025-001",
        status="completed",
        status_description="All steps completed",
        can_reverse=True,
        can_post=False,
        is_locked=False,
        progress_percent=100,
        current_step=5,
        total_steps=5,
        errors=[],
        warnings=[],
    )
    svc.reverse_consolidation.return_value = MagicMock(
        consolidation_number="CON-2025-001",
        status="reversed",
    )

    # Report responses
    svc.get_consolidated_balance_sheet.return_value = MagicMock(
        group_name="Test Group",
        as_of_date=date.today(),
        reporting_currency="IDR",
        assets={"current": {"cash": 10000}},
        liabilities={"current": {"payables": 5000}},
        equity={"parent": 20000, "nci": 500},
        total_assets=Decimal("50000"),
        total_liabilities=Decimal("20000"),
        total_equity=Decimal("30000"),
        nci=Decimal("500"),
        is_balanced=True,
    )
    svc.get_consolidated_income_statement.return_value = MagicMock(
        group_name="Test Group",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        reporting_currency="IDR",
        revenues={"sales": 10000},
        cost_of_goods_sold={"cogs": 6000},
        gross_profit=Decimal("4000"),
        operating_expenses={"admin": 2000},
        operating_income=Decimal("2000"),
        other_income={"interest": 100},
        other_expenses={"tax": 100},
        income_before_tax=Decimal("2000"),
        tax_expense=Decimal("0"),
        net_income=Decimal("2000"),
        nci_share=Decimal("500"),
        parent_share=Decimal("1500"),
    )
    svc.get_complete_consolidation_report.return_value = MagicMock(
        group_name="Test Group",
        fiscal_year=2025,
        period=1,
        as_of_date=date.today(),
        reporting_currency="IDR",
        balance_sheet=MagicMock(
            total_assets=Decimal("50000"),
            total_liabilities=Decimal("20000"),
            total_equity=Decimal("30000"),
            nci=Decimal("500"),
            details={},
        ),
        income_statement=MagicMock(
            total_revenue=Decimal("10000"),
            total_expense=Decimal("8000"),
            net_income=Decimal("2000"),
            nci_share=Decimal("500"),
            parent_share=Decimal("1500"),
            details={},
        ),
        elimination_entries=[],
        intercompany_transactions=[],
        nci_calculation={},
    )

    # Export
    svc.export_consolidation_report.return_value = (b"excel data", "report.xlsx")

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
        key1 = manager._get_key("abc", "create_group")
        key2 = manager._get_key("abc", "create_group")
        key3 = manager._get_key("abc", "update_group")
        assert key1 == key2
        assert key1 != key3


# =============================================================================
# Tests for Enums
# =============================================================================

class TestEnums:
    def test_consolidation_method_values(self):
        assert ConsolidationMethod.FULL.value == "full"
        assert ConsolidationMethod.EQUITY.value == "equity"
        assert ConsolidationMethod.PROPORTIONAL.value == "proportional"
        assert ConsolidationMethod.COST.value == "cost"

    def test_intercompany_type_values(self):
        assert IntercompanyType.SALES.value == "sales"
        assert IntercompanyType.SERVICE.value == "service"
        assert IntercompanyType.LOAN.value == "loan"
        assert IntercompanyType.INTEREST.value == "interest"
        assert IntercompanyType.DIVIDEND.value == "dividend"
        assert IntercompanyType.FUND_TRANSFER.value == "fund_transfer"
        assert IntercompanyType.ASSET_TRANSFER.value == "asset_transfer"
        assert IntercompanyType.EXPENSE_ALLOCATION.value == "expense_allocation"
        assert IntercompanyType.MANAGEMENT_FEE.value == "management_fee"
        assert IntercompanyType.ROYALTY.value == "royalty"

    def test_elimination_status_values(self):
        assert EliminationStatus.PENDING.value == "pending"
        assert EliminationStatus.ELIMINATED.value == "eliminated"
        assert EliminationStatus.PARTIALLY_ELIMINATED.value == "partially_eliminated"
        assert EliminationStatus.ADJUSTED.value == "adjusted"
        assert EliminationStatus.CANCELLED.value == "cancelled"

    def test_consolidation_status_values(self):
        assert ConsolidationStatus.DRAFT.value == "draft"
        assert ConsolidationStatus.IN_PROGRESS.value == "in_progress"
        assert ConsolidationStatus.COMPLETED.value == "completed"
        assert ConsolidationStatus.APPROVED.value == "approved"
        assert ConsolidationStatus.REVERSED.value == "reversed"
        assert ConsolidationStatus.LOCKED.value == "locked"
        assert ConsolidationStatus.CANCELLED.value == "cancelled"

    def test_currency_translation_method_values(self):
        assert CurrencyTranslationMethod.CURRENT_RATE.value == "current_rate"
        assert CurrencyTranslationMethod.HISTORICAL_RATE.value == "historical_rate"
        assert CurrencyTranslationMethod.AVERAGE_RATE.value == "average_rate"


# =============================================================================
# Tests for Schemas (validation)
# =============================================================================

class TestConsolidationGroupCreateSchema:
    def test_valid_schema(self):
        data = {
            "group_code": "GRP-001",
            "group_name": "Test Group",
            "parent_entity_id": uuid4(),
            "functional_currency": "IDR",
            "description": "Test",
            "fiscal_year_start": 1,
        }
        schema = ConsolidationGroupCreateSchema(**data)
        assert schema.group_code == "GRP-001"
        assert schema.group_name == "Test Group"
        assert schema.functional_currency == "IDR"

    def test_group_code_uppercase(self):
        data = {
            "group_code": "grp-001",
            "group_name": "Test",
            "functional_currency": "IDR",
        }
        schema = ConsolidationGroupCreateSchema(**data)
        assert schema.group_code == "GRP-001"

    def test_group_code_required(self):
        with pytest.raises(ValueError, match="Group code is required"):
            ConsolidationGroupCreateSchema(
                group_code="",
                group_name="Test",
                functional_currency="IDR",
            )


class TestConsolidationMemberSchema:
    def test_valid_schema(self):
        data = {
            "legal_entity_id": uuid4(),
            "ownership_percentage": Decimal("75.00"),
            "consolidation_method": ConsolidationMethod.FULL,
            "effective_date": date.today(),
            "notes": "Test",
        }
        schema = ConsolidationMemberSchema(**data)
        assert schema.ownership_percentage == Decimal("75.00")
        assert schema.consolidation_method == ConsolidationMethod.FULL

    def test_ownership_percentage_bounds(self):
        with pytest.raises(ValueError):
            ConsolidationMemberSchema(
                legal_entity_id=uuid4(),
                ownership_percentage=Decimal("101.00"),
                consolidation_method=ConsolidationMethod.FULL,
            )
        with pytest.raises(ValueError):
            ConsolidationMemberSchema(
                legal_entity_id=uuid4(),
                ownership_percentage=Decimal("-1.00"),
                consolidation_method=ConsolidationMethod.FULL,
            )


class TestIntercompanyTransactionCreateSchema:
    def test_valid_schema(self):
        from_id = uuid4()
        to_id = uuid4()
        data = {
            "from_legal_entity_id": from_id,
            "to_legal_entity_id": to_id,
            "transaction_date": date.today(),
            "amount": Decimal("1000.00"),
            "currency": "IDR",
            "exchange_rate": Decimal("1.0"),
            "transaction_type": IntercompanyType.SALES,
            "description": "Test",
            "reference_number": "REF-001",
            "invoice_number": "INV-001",
            "notes": "Test notes",
        }
        schema = IntercompanyTransactionCreateSchema(**data)
        assert schema.from_legal_entity_id == from_id
        assert schema.to_legal_entity_id == to_id
        assert schema.amount == Decimal("1000.00")

    def test_same_entity_invalid(self):
        entity_id = uuid4()
        with pytest.raises(ValueError, match="From and to legal entities must be different"):
            IntercompanyTransactionCreateSchema(
                from_legal_entity_id=entity_id,
                to_legal_entity_id=entity_id,
                transaction_date=date.today(),
                amount=Decimal("1000"),
                transaction_type=IntercompanyType.SALES,
                description="Test",
            )

    def test_positive_amount_required(self):
        from_id = uuid4()
        to_id = uuid4()
        with pytest.raises(ValueError):
            IntercompanyTransactionCreateSchema(
                from_legal_entity_id=from_id,
                to_legal_entity_id=to_id,
                transaction_date=date.today(),
                amount=Decimal("0"),
                transaction_type=IntercompanyType.SALES,
                description="Test",
            )


class TestEliminationEntryCreateSchema:
    def test_valid_schema(self):
        data = {
            "consolidation_group_id": uuid4(),
            "fiscal_year": 2025,
            "period": 1,
            "intercompany_transaction_ids": [uuid4(), uuid4()],
            "notes": "Test",
        }
        schema = EliminationEntryCreateSchema(**data)
        assert schema.fiscal_year == 2025
        assert schema.period == 1
        assert len(schema.intercompany_transaction_ids) == 2


class TestNCICalculationSchema:
    def test_valid_schema(self):
        data = {
            "consolidation_group_id": uuid4(),
            "fiscal_year": 2025,
            "period": 1,
            "net_income": Decimal("1000"),
            "dividends_declared": Decimal("100"),
            "other_comprehensive_income": Decimal("50"),
        }
        schema = NCICalculationSchema(**data)
        assert schema.net_income == Decimal("1000")


class TestConsolidationRunRequestSchema:
    def test_valid_schema(self):
        data = {
            "consolidation_group_id": uuid4(),
            "fiscal_year": 2025,
            "period": 1,
            "include_nci": True,
            "translation_method": CurrencyTranslationMethod.CURRENT_RATE,
            "reporting_currency": "USD",
            "as_of_date": date.today(),
            "post_eliminations": True,
        }
        schema = ConsolidationRunRequestSchema(**data)
        assert schema.reporting_currency == "USD"
        assert schema.translation_method == CurrencyTranslationMethod.CURRENT_RATE


# =============================================================================
# Tests for Endpoint Functions (with mocks)
# =============================================================================

@pytest.mark.asyncio
class TestConsolidationGroupEndpoints:
    async def test_create_group_success(self, mock_consolidation_service, mock_token_payload):
        request = ConsolidationGroupCreateSchema(
            group_code="GRP-001",
            group_name="Test Group",
            functional_currency="IDR",
        )
        result = await create_consolidation_group(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            service=mock_consolidation_service,
        )
        assert isinstance(result, ConsolidationGroupResponseSchema)
        assert result.group_code == "GRP-001"
        mock_consolidation_service.create_group.assert_called_once()

    async def test_create_group_idempotency(self, mock_consolidation_service, mock_token_payload):
        request = ConsolidationGroupCreateSchema(
            group_code="GRP-001",
            group_name="Test",
            functional_currency="IDR",
        )
        with patch("adapters.primary_api.v1.fastapi_consolidation_router._idempotency_manager") as mock_im:
            mock_im.get_cached_result.return_value = {
                "id": str(uuid4()),
                "group_code": "GRP-001",
                "group_name": "Test",
                "parent_entity_id": None,
                "parent_entity_name": None,
                "functional_currency": "IDR",
                "description": None,
                "is_active": True,
                "member_count": 0,
                "fiscal_year_start": 1,
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
                "created_by": str(uuid4()),
                "created_by_name": None,
                "version": 1,
            }
            result = await create_consolidation_group(
                request=request,
                idempotency_key="abc123",
                _permission=None,
                current_user=mock_token_payload,
                service=mock_consolidation_service,
            )
            assert isinstance(result, ConsolidationGroupResponseSchema)
            mock_consolidation_service.create_group.assert_not_called()

    async def test_list_groups(self, mock_consolidation_service):
        result = await list_consolidation_groups(
            is_active=True,
            _permission=None,
            service=mock_consolidation_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], ConsolidationGroupResponseSchema)
        mock_consolidation_service.list_groups.assert_called_once_with(is_active=True)

    async def test_get_group_success(self, mock_consolidation_service):
        group_id = uuid4()
        result = await get_consolidation_group(
            group_id=group_id,
            _permission=None,
            service=mock_consolidation_service,
        )
        assert isinstance(result, ConsolidationGroupResponseSchema)
        mock_consolidation_service.get_group_by_id.assert_called_once_with(group_id)

    async def test_get_group_not_found(self, mock_consolidation_service):
        mock_consolidation_service.get_group_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_consolidation_group(
                group_id=uuid4(),
                _permission=None,
                service=mock_consolidation_service,
            )
        assert exc.value.status_code == 404

    async def test_update_group_success(self, mock_consolidation_service, mock_token_payload):
        group_id = uuid4()
        request = ConsolidationGroupUpdateSchema(group_name="Updated Name")
        result = await update_consolidation_group(
            group_id=group_id,
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            service=mock_consolidation_service,
        )
        assert isinstance(result, ConsolidationGroupResponseSchema)
        mock_consolidation_service.update_group.assert_called_once()

    async def test_update_group_not_found(self, mock_consolidation_service, mock_token_payload):
        mock_consolidation_service.update_group.return_value = None
        with pytest.raises(HTTPException) as exc:
            await update_consolidation_group(
                group_id=uuid4(),
                request=ConsolidationGroupUpdateSchema(),
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                service=mock_consolidation_service,
            )
        assert exc.value.status_code == 404

    async def test_deactivate_group_success(self, mock_consolidation_service, mock_token_payload):
        group_id = uuid4()
        result = await deactivate_consolidation_group(
            group_id=group_id,
            _permission=None,
            current_user=mock_token_payload,
            service=mock_consolidation_service,
        )
        assert result["is_active"] is False
        mock_consolidation_service.deactivate_group.assert_called_once_with(group_id, mock_token_payload.user_id)

    async def test_deactivate_group_not_found(self, mock_consolidation_service, mock_token_payload):
        mock_consolidation_service.deactivate_group.return_value = None
        with pytest.raises(HTTPException) as exc:
            await deactivate_consolidation_group(
                group_id=uuid4(),
                _permission=None,
                current_user=mock_token_payload,
                service=mock_consolidation_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestGroupMemberEndpoints:
    async def test_add_member(self, mock_consolidation_service, mock_token_payload):
        group_id = uuid4()
        request = ConsolidationMemberSchema(
            legal_entity_id=uuid4(),
            ownership_percentage=Decimal("75.00"),
            consolidation_method=ConsolidationMethod.FULL,
        )
        result = await add_group_member(
            group_id=group_id,
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            service=mock_consolidation_service,
        )
        assert isinstance(result, ConsolidationMemberResponseSchema)
        assert result.ownership_percentage == Decimal("75.00")
        mock_consolidation_service.add_member.assert_called_once()

    async def test_list_members(self, mock_consolidation_service):
        group_id = uuid4()
        result = await list_group_members(
            group_id=group_id,
            _permission=None,
            service=mock_consolidation_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], ConsolidationMemberResponseSchema)
        mock_consolidation_service.get_group_members.assert_called_once_with(group_id)

    async def test_update_member(self, mock_consolidation_service, mock_token_payload):
        group_id = uuid4()
        member_id = uuid4()
        result = await update_group_member(
            group_id=group_id,
            member_id=member_id,
            ownership_percentage=Decimal("80.00"),
            consolidation_method=ConsolidationMethod.EQUITY,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            service=mock_consolidation_service,
        )
        assert isinstance(result, ConsolidationMemberResponseSchema)
        mock_consolidation_service.update_member.assert_called_once_with(
            member_id=member_id,
            group_id=group_id,
            ownership_percentage=Decimal("80.00"),
            consolidation_method="equity",
            updated_by=mock_token_payload.user_id,
        )

    async def test_remove_member(self, mock_consolidation_service, mock_token_payload):
        group_id = uuid4()
        member_id = uuid4()
        result = await remove_group_member(
            group_id=group_id,
            member_id=member_id,
            _permission=None,
            current_user=mock_token_payload,
            service=mock_consolidation_service,
        )
        assert result["removed"] is True
        mock_consolidation_service.remove_member.assert_called_once_with(
            member_id, group_id, mock_token_payload.user_id
        )


@pytest.mark.asyncio
class TestIntercompanyTransactionEndpoints:
    async def test_create_transaction(self, mock_consolidation_service, mock_token_payload):
        from_id = uuid4()
        to_id = uuid4()
        request = IntercompanyTransactionCreateSchema(
            from_legal_entity_id=from_id,
            to_legal_entity_id=to_id,
            transaction_date=date.today(),
            amount=Decimal("1000"),
            transaction_type=IntercompanyType.SALES,
            description="Test",
        )
        result = await create_intercompany_transaction(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            service=mock_consolidation_service,
        )
        assert isinstance(result, IntercompanyTransactionResponseSchema)
        assert result.amount == Decimal("1000")
        mock_consolidation_service.create_intercompany_transaction.assert_called_once()

    async def test_list_transactions(self, mock_consolidation_service):
        result = await list_intercompany_transactions(
            from_legal_entity_id=None,
            to_legal_entity_id=None,
            transaction_type=IntercompanyType.SALES,
            elimination_status=EliminationStatus.PENDING,
            start_date=None,
            end_date=None,
            page=1,
            page_size=50,
            _permission=None,
            service=mock_consolidation_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], IntercompanyTransactionResponseSchema)
        mock_consolidation_service.list_intercompany_transactions.assert_called_once()

    async def test_get_transaction_success(self, mock_consolidation_service):
        tx_id = uuid4()
        result = await get_intercompany_transaction(
            transaction_id=tx_id,
            _permission=None,
            service=mock_consolidation_service,
        )
        assert isinstance(result, IntercompanyTransactionResponseSchema)
        mock_consolidation_service.get_intercompany_transaction_by_id.assert_called_once_with(tx_id)

    async def test_get_transaction_not_found(self, mock_consolidation_service):
        mock_consolidation_service.get_intercompany_transaction_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_intercompany_transaction(
                transaction_id=uuid4(),
                _permission=None,
                service=mock_consolidation_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestEliminationEndpoints:
    async def test_generate_elimination(self, mock_consolidation_service, mock_token_payload):
        request = EliminationEntryCreateSchema(
            consolidation_group_id=uuid4(),
            fiscal_year=2025,
            period=1,
            intercompany_transaction_ids=[uuid4()],
        )
        result = await generate_elimination_entries(
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            service=mock_consolidation_service,
        )
        assert isinstance(result, EliminationEntryResponseSchema)
        assert result.fiscal_year == 2025
        mock_consolidation_service.generate_elimination_entries.assert_called_once()

    async def test_post_elimination(self, mock_consolidation_service, mock_token_payload):
        elim_id = uuid4()
        result = await post_elimination_entry(
            elimination_id=elim_id,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            service=mock_consolidation_service,
        )
        assert isinstance(result, EliminationEntryResponseSchema)
        mock_consolidation_service.post_elimination_entry.assert_called_once_with(elim_id, mock_token_payload.user_id)

    async def test_list_eliminations(self, mock_consolidation_service):
        result = await list_elimination_entries(
            consolidation_group_id=None,
            fiscal_year=2025,
            period=None,
            status=EliminationStatus.PENDING,
            _permission=None,
            service=mock_consolidation_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], EliminationEntryResponseSchema)
        mock_consolidation_service.list_elimination_entries.assert_called_once()


@pytest.mark.asyncio
class TestNCIEndpoints:
    async def test_calculate_nci(self, mock_consolidation_service, mock_token_payload):
        request = NCICalculationSchema(
            consolidation_group_id=uuid4(),
            fiscal_year=2025,
            period=1,
            net_income=Decimal("1000"),
        )
        result = await calculate_nci(
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            service=mock_consolidation_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], NCIResponseSchema)
        mock_consolidation_service.calculate_nci.assert_called_once()


@pytest.mark.asyncio
class TestConsolidationRunEndpoints:
    async def test_run_consolidation(self, mock_consolidation_service, mock_token_payload):
        request = ConsolidationRunRequestSchema(
            consolidation_group_id=uuid4(),
            fiscal_year=2025,
            period=1,
        )
        result = await run_consolidation(
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            service=mock_consolidation_service,
        )
        assert isinstance(result, ConsolidationRunResponseSchema)
        assert result.fiscal_year == 2025
        mock_consolidation_service.run_consolidation.assert_called_once()

    async def test_get_history(self, mock_consolidation_service):
        result = await get_consolidation_history(
            consolidation_group_id=None,
            fiscal_year=None,
            status=None,
            page=1,
            page_size=20,
            _permission=None,
            service=mock_consolidation_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], ConsolidationRunResponseSchema)

    async def test_get_status(self, mock_consolidation_service):
        cons_id = uuid4()
        result = await get_consolidation_status(
            consolidation_id=cons_id,
            _permission=None,
            service=mock_consolidation_service,
        )
        assert result["status"] == "completed"
        assert result["can_reverse"] is True
        mock_consolidation_service.get_consolidation_status.assert_called_once_with(cons_id)

    async def test_reverse_consolidation(self, mock_consolidation_service, mock_token_payload):
        cons_id = uuid4()
        result = await reverse_consolidation(
            consolidation_id=cons_id,
            reason="Test reversal",
            _permission=None,
            current_user=mock_token_payload,
            service=mock_consolidation_service,
        )
        assert result["reversed"] is True
        mock_consolidation_service.reverse_consolidation.assert_called_once_with(
            consolidation_id=cons_id,
            reason="Test reversal",
            reversed_by=mock_token_payload.user_id,
        )

    async def test_reverse_not_found(self, mock_consolidation_service, mock_token_payload):
        mock_consolidation_service.reverse_consolidation.return_value = None
        with pytest.raises(HTTPException) as exc:
            await reverse_consolidation(
                consolidation_id=uuid4(),
                reason="Test",
                _permission=None,
                current_user=mock_token_payload,
                service=mock_consolidation_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestReportEndpoints:
    async def test_balance_sheet(self, mock_consolidation_service):
        cons_id = uuid4()
        result = await get_consolidated_balance_sheet(
            consolidation_id=cons_id,
            _permission=None,
            service=mock_consolidation_service,
        )
        assert isinstance(result, BalanceSheetConsolidatedSchema)
        assert result.total_assets == Decimal("50000")
        assert result.is_balanced is True
        mock_consolidation_service.get_consolidated_balance_sheet.assert_called_once_with(cons_id)

    async def test_balance_sheet_not_found(self, mock_consolidation_service):
        mock_consolidation_service.get_consolidated_balance_sheet.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_consolidated_balance_sheet(
                consolidation_id=uuid4(),
                _permission=None,
                service=mock_consolidation_service,
            )
        assert exc.value.status_code == 404

    async def test_income_statement(self, mock_consolidation_service):
        cons_id = uuid4()
        result = await get_consolidated_income_statement(
            consolidation_id=cons_id,
            _permission=None,
            service=mock_consolidation_service,
        )
        assert isinstance(result, IncomeStatementConsolidatedSchema)
        assert result.net_income == Decimal("2000")
        mock_consolidation_service.get_consolidated_income_statement.assert_called_once_with(cons_id)

    async def test_complete_report(self, mock_consolidation_service):
        cons_id = uuid4()
        result = await get_consolidation_report(
            consolidation_id=cons_id,
            _permission=None,
            service=mock_consolidation_service,
        )
        assert "balance_sheet" in result
        assert result["fiscal_year"] == 2025
        mock_consolidation_service.get_complete_consolidation_report.assert_called_once_with(cons_id)


@pytest.mark.asyncio
class TestExportEndpoint:
    async def test_export_excel(self, mock_consolidation_service):
        cons_id = uuid4()
        response = await export_consolidation_report(
            consolidation_id=cons_id,
            format="excel",
            _permission=None,
            service=mock_consolidation_service,
        )
        assert response.body == b"excel data"
        assert "attachment" in response.headers["Content-Disposition"]
        assert response.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        mock_consolidation_service.export_consolidation_report.assert_called_once_with(
            consolidation_id=cons_id,
            format="excel",
        )

    async def test_export_pdf(self, mock_consolidation_service):
        cons_id = uuid4()
        mock_consolidation_service.export_consolidation_report.return_value = (b"pdf data", "report.pdf")
        response = await export_consolidation_report(
            consolidation_id=cons_id,
            format="pdf",
            _permission=None,
            service=mock_consolidation_service,
        )
        assert response.media_type == "application/pdf"
