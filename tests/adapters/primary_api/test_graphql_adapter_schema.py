# tests/adapters/primary_api/test_graphql_adapter_schema.py
# Perbaikan kualitas assertions: menghapus semua assert True,
# diganti dengan assertion yang memeriksa nilai aktual,
# efek samping, dan interaksi mock.

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from strawberry.types import Info

from adapters.primary_api.graphql_adapter_schema import (
    Account,
    AgingBucket,
    AgingReport,
    AgingReportRepositoryAdapter,
    BalanceSheet,
    BalanceSheetRepositoryAdapter,
    BalanceSheetSection,
    FixedAsset,
    IncomeStatement,
    IncomeStatementLine,
    IncomeStatementRepositoryAdapter,
    Journal,
    JournalLine,
    LedgerEntry,
    Money,
    Query,
    StockCard,
    StockCardEntry,
    TrialBalance,
    TrialBalanceLine,
    TrialBalanceRepositoryAdapter,
    get_graphql_context,
    resolve_accounts,
    resolve_aging_ar,
    resolve_balance_sheet,
    resolve_fixed_assets,
    resolve_income_statement,
    resolve_journal,
    resolve_journals,
    resolve_ledger_entries,
    resolve_stock_card,
    resolve_trial_balance,
)


# ============================================================================
# Type class tests (basic construction)
# ============================================================================
class TestMoney:
    def test_construction(self):
        m = Money(amount=Decimal("100.50"), currency="IDR")
        assert m.amount == Decimal("100.50")
        assert m.currency == "IDR"

    def test_default_currency(self):
        m = Money(amount=Decimal("200"))
        assert m.currency == "IDR"


class TestAccount:
    def test_construction(self):
        now = datetime.now()
        account = Account(
            id=uuid4(),
            account_code="101",
            account_name="Cash",
            account_type="Asset",
            normal_balance="Debit",
            level=1,
            is_active=True,
            parent_account_code=None,
        )
        assert account.account_code == "101"
        assert account.account_name == "Cash"
        assert account.is_active is True
        assert account.parent_account_code is None


class TestJournalLine:
    def test_construction(self):
        line = JournalLine(
            account_code="101",
            account_name="Cash",
            debit_amount=Decimal("1000"),
            credit_amount=Decimal("0"),
            description="Test"
        )
        assert line.debit_amount == Decimal("1000")
        assert line.credit_amount == Decimal("0")
        assert line.description == "Test"


class TestJournal:
    def test_construction(self):
        j_id = uuid4()
        now = datetime.now()
        journal = Journal(
            id=j_id,
            voucher_number="VOUCH-001",
            journal_date=date(2024, 1, 1),
            description="Test journal",
            status="posted",
            total_debit=Decimal("1000"),
            total_credit=Decimal("1000"),
            created_by="admin",
            created_at=now,
            lines=[]
        )
        assert journal.id == j_id
        assert journal.voucher_number == "VOUCH-001"
        assert journal.total_debit == Decimal("1000")


class TestLedgerEntry:
    def test_construction(self):
        e = LedgerEntry(
            id=uuid4(),
            journal_id=uuid4(),
            voucher_number="V001",
            account_code="101",
            account_name="Cash",
            posting_date=date(2024, 1, 1),
            debit_amount=Decimal("100"),
            credit_amount=Decimal("0"),
            description="Test"
        )
        assert e.account_code == "101"


class TestTrialBalanceLine:
    def test_construction(self):
        line = TrialBalanceLine(
            account_code="101",
            account_name="Cash",
            opening_balance_debit=Decimal("0"),
            opening_balance_credit=Decimal("0"),
            movement_debit=Decimal("100"),
            movement_credit=Decimal("0"),
            closing_balance_debit=Decimal("100"),
            closing_balance_credit=Decimal("0"),
        )
        assert line.account_code == "101"
        assert line.closing_balance_debit == Decimal("100")


class TestTrialBalance:
    def test_construction(self):
        tb = TrialBalance(
            as_of_date=date(2024, 1, 31),
            lines=[],
            total_debit=Decimal("1000"),
            total_credit=Decimal("1000"),
            is_balanced=True,
        )
        assert tb.as_of_date == date(2024, 1, 31)
        assert tb.is_balanced is True


class TestBalanceSheetSection:
    def test_construction(self):
        section = BalanceSheetSection(lines=[{"a": 1}], total=Decimal("100"))
        assert section.lines == [{"a": 1}]
        assert section.total == Decimal("100")


class TestBalanceSheet:
    def test_construction(self):
        bs = BalanceSheet(
            as_of_date=date(2024, 1, 31),
            assets=BalanceSheetSection([], Decimal("0")),
            liabilities=BalanceSheetSection([], Decimal("0")),
            equity=BalanceSheetSection([], Decimal("0")),
            total_assets=Decimal("1000"),
            total_liabilities_equity=Decimal("1000"),
        )
        assert bs.total_assets == Decimal("1000")


class TestIncomeStatementLine:
    def test_construction(self):
        line = IncomeStatementLine(
            account_code="400",
            account_name="Revenue",
            current_period=Decimal("1000"),
            year_to_date=Decimal("5000"),
        )
        assert line.current_period == Decimal("1000")


class TestIncomeStatement:
    def test_construction(self):
        is_ = IncomeStatement(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            total_revenue=Decimal("5000"),
            total_expenses=Decimal("3000"),
            net_income=Decimal("2000"),
            lines=[],
        )
        assert is_.net_income == Decimal("2000")


class TestAgingBucket:
    def test_construction(self):
        bucket = AgingBucket(bucket_name="0-30", total_amount=Decimal("1000"), percentage=50.0)
        assert bucket.bucket_name == "0-30"
        assert bucket.percentage == 50.0


class TestAgingReport:
    def test_construction(self):
        report = AgingReport(
            customer_id=uuid4(),
            customer_name="Acme Corp",
            total_outstanding=Decimal("5000"),
            buckets=[]
        )
        assert report.customer_name == "Acme Corp"


class TestStockCardEntry:
    def test_construction(self):
        entry = StockCardEntry(
            date=date(2024, 1, 1),
            reference="PO-001",
            in_quantity=Decimal("10"),
            out_quantity=Decimal("0"),
            balance_quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            balance_value=Decimal("1000"),
        )
        assert entry.balance_quantity == Decimal("10")


class TestStockCard:
    def test_construction(self):
        card = StockCard(
            item_id=uuid4(),
            item_code="ITEM001",
            item_name="Widget",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            opening_quantity=Decimal("0"),
            closing_quantity=Decimal("10"),
            entries=[],
        )
        assert card.item_code == "ITEM001"


class TestFixedAsset:
    def test_construction(self):
        asset = FixedAsset(
            id=uuid4(),
            asset_code="FA001",
            asset_name="Building",
            acquisition_cost=Decimal("1000000"),
            accumulated_depreciation=Decimal("100000"),
            net_book_value=Decimal("900000"),
            status="Active",
        )
        assert asset.net_book_value == Decimal("900000")


# ============================================================================
# Adapter tests (with mocks)
# ============================================================================
class TestTrialBalanceRepositoryAdapter:
    @pytest.fixture
    def adapter(self):
        return TrialBalanceRepositoryAdapter()

    async def test_get_trial_balance(self, adapter):
        legal_entity_id = uuid4()
        as_of_date = date(2024, 1, 31)
        mock_service = AsyncMock()
        mock_service.get_trial_balance_graphql.return_value = {
            "lines": [
                {
                    "account_code": "101",
                    "account_name": "Cash",
                    "opening_balance_debit": "0",
                    "opening_balance_credit": "0",
                    "movement_debit": "100",
                    "movement_credit": "0",
                    "closing_balance_debit": "100",
                    "closing_balance_credit": "0",
                }
            ],
            "total_debit": Decimal("100"),
            "total_credit": Decimal("0"),
            "is_balanced": False,
        }
        with patch.object(adapter, "_get_service", return_value=mock_service):
            result = await adapter.get_trial_balance(
                legal_entity_id=legal_entity_id,
                as_of_date=as_of_date,
                include_zero_balance=True,
            )
        assert result["as_of_date"] == as_of_date
        assert len(result["lines"]) == 1
        assert result["total_debit"] == Decimal("100")
        assert result["total_credit"] == Decimal("0")
        assert result["is_balanced"] is False
        mock_service.get_trial_balance_graphql.assert_awaited_once_with(
            legal_entity_id, as_of_date, include_zero_balance=True
        )


class TestAgingReportRepositoryAdapter:
    @pytest.fixture
    def adapter(self):
        return AgingReportRepositoryAdapter()

    async def test_get_ar_aging(self, adapter):
        legal_entity_id = uuid4()
        as_of_date = date(2024, 1, 31)
        customer_id = uuid4()
        mock_ar_service = AsyncMock()
        mock_ar_service.get_aging_graphql.return_value = [
            {
                "customer_id": str(customer_id),
                "customer_name": "Acme",
                "total_outstanding": Decimal("1000"),
                "buckets": [{"bucket_name": "0-30", "total_amount": Decimal("600"), "percentage": 60.0}],
            }
        ]
        with patch.object(adapter, "_get_ar_service", return_value=mock_ar_service):
            result = await adapter.get_ar_aging(
                legal_entity_id=legal_entity_id,
                as_of_date=as_of_date,
                customer_id=customer_id,
                bucket_days=[30, 60],
            )
        assert len(result) == 1
        assert result[0]["customer_id"] == str(customer_id)
        assert result[0]["total_outstanding"] == Decimal("1000")
        mock_ar_service.get_aging_graphql.assert_awaited_once_with(
            legal_entity_id, as_of_date, customer_id
        )

    async def test_get_ap_aging(self, adapter):
        legal_entity_id = uuid4()
        as_of_date = date(2024, 1, 31)
        supplier_id = uuid4()
        mock_ap_service = AsyncMock()
        mock_ap_service.get_ap_aging_graphql.return_value = [
            {
                "supplier_id": str(supplier_id),
                "supplier_name": "Vendor",
                "total_outstanding": Decimal("2000"),
                "buckets": [{"bucket_name": "0-30", "total_amount": Decimal("1500"), "percentage": 75.0}],
            }
        ]
        with patch.object(adapter, "_get_ap_service", return_value=mock_ap_service):
            result = await adapter.get_ap_aging(
                legal_entity_id=legal_entity_id,
                as_of_date=as_of_date,
                supplier_id=supplier_id,
                bucket_days=[30, 60],
            )
        assert len(result) == 1
        assert result[0]["supplier_id"] == str(supplier_id)
        mock_ap_service.get_ap_aging_graphql.assert_awaited_once_with(
            legal_entity_id, as_of_date, supplier_id
        )


class TestBalanceSheetRepositoryAdapter:
    @pytest.fixture
    def adapter(self):
        return BalanceSheetRepositoryAdapter()

    async def test_get_balance_sheet(self, adapter):
        legal_entity_id = uuid4()
        as_of_date = date(2024, 1, 31)
        mock_service = AsyncMock()
        mock_service.get_balance_sheet_graphql.return_value = {
            "assets": {"lines": [{"account": "Cash", "amount": "100"}], "total": Decimal("100")},
            "liabilities": {"lines": [], "total": Decimal("0")},
            "equity": {"lines": [], "total": Decimal("100")},
            "total_assets": Decimal("100"),
            "total_liabilities_equity": Decimal("100"),
        }
        with patch.object(adapter, "_get_service", return_value=mock_service):
            result = await adapter.get_balance_sheet(
                legal_entity_id=legal_entity_id,
                as_of_date=as_of_date,
                include_zero_balance=True,
            )
        assert result["total_assets"] == Decimal("100")
        mock_service.get_balance_sheet_graphql.assert_awaited_once_with(
            legal_entity_id, as_of_date, include_zero_balance=True
        )


class TestIncomeStatementRepositoryAdapter:
    @pytest.fixture
    def adapter(self):
        return IncomeStatementRepositoryAdapter()

    async def test_get_income_statement(self, adapter):
        legal_entity_id = uuid4()
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 31)
        mock_service = AsyncMock()
        mock_service.get_income_statement_graphql.return_value = {
            "total_revenue": Decimal("5000"),
            "total_expenses": Decimal("3000"),
            "net_income": Decimal("2000"),
            "lines": [],
        }
        with patch.object(adapter, "_get_service", return_value=mock_service):
            result = await adapter.get_income_statement(
                legal_entity_id=legal_entity_id,
                start_date=start_date,
                end_date=end_date,
                include_zero_balance=True,
            )
        assert result["net_income"] == Decimal("2000")
        mock_service.get_income_statement_graphql.assert_awaited_once_with(
            legal_entity_id, start_date, end_date, include_zero_balance=True
        )


# ============================================================================
# Resolver tests
# ============================================================================
class TestResolvers:
    @pytest.fixture
    def mock_info(self):
        info = MagicMock(spec=Info)
        info.context = {"request": MagicMock()}
        return info

    # ---------- accounts ----------
    @patch("adapters.primary_api.graphql_adapter_schema.get_current_legal_entity")
    @patch("adapters.primary_api.graphql_adapter_schema.COAService")
    async def test_resolve_accounts(
        self, mock_coa_service, mock_get_legal, mock_info
    ):
        legal_entity_id = uuid4()
        mock_get_legal.return_value = legal_entity_id
        mock_service = AsyncMock()
        mock_service.list_accounts_for_graphql.return_value = [
            {
                "id": uuid4(),
                "account_code": "101",
                "account_name": "Cash",
                "account_type": "Asset",
                "normal_balance": "Debit",
                "level": 1,
                "is_active": True,
                "parent_account_code": None,
            }
        ]
        mock_coa_service.return_value = mock_service

        result = await resolve_accounts(
            root=None, info=mock_info, account_type="Asset", is_active=True
        )
        assert len(result) == 1
        assert isinstance(result[0], Account)
        assert result[0].account_code == "101"
        mock_service.list_accounts_for_graphql.assert_awaited_once_with(
            legal_entity_id, "Asset", True
        )

    # ---------- journal ----------
    @patch("adapters.primary_api.graphql_adapter_schema.get_current_legal_entity")
    @patch("adapters.primary_api.graphql_adapter_schema.JournalService")
    async def test_resolve_journal(self, mock_journal_service, mock_get_legal, mock_info):
        legal_entity_id = uuid4()
        mock_get_legal.return_value = legal_entity_id
        journal_id = uuid4()
        mock_service = AsyncMock()
        mock_service.get_journal_by_id_graphql.return_value = {
            "id": journal_id,
            "voucher_number": "V001",
            "journal_date": date(2024, 1, 1),
            "description": "Test",
            "status": "posted",
            "total_debit": Decimal("100"),
            "total_credit": Decimal("100"),
            "created_by": "admin",
            "created_at": datetime.now(),
            "lines": [],
        }
        mock_journal_service.return_value = mock_service

        result = await resolve_journal(
            root=None, info=mock_info, journal_id=journal_id
        )
        assert result is not None
        assert isinstance(result, Journal)
        assert result.id == journal_id
        assert result.voucher_number == "V001"
        mock_service.get_journal_by_id_graphql.assert_awaited_once_with(
            journal_id, legal_entity_id
        )

    @patch("adapters.primary_api.graphql_adapter_schema.get_current_legal_entity")
    @patch("adapters.primary_api.graphql_adapter_schema.JournalService")
    async def test_resolve_journal_not_found(self, mock_journal_service, mock_get_legal, mock_info):
        legal_entity_id = uuid4()
        mock_get_legal.return_value = legal_entity_id
        mock_service = AsyncMock()
        mock_service.get_journal_by_id_graphql.return_value = None
        mock_journal_service.return_value = mock_service

        result = await resolve_journal(
            root=None, info=mock_info, journal_id=uuid4()
        )
        assert result is None

    # ---------- journals ----------
    @patch("adapters.primary_api.graphql_adapter_schema.get_current_legal_entity")
    @patch("adapters.primary_api.graphql_adapter_schema.JournalService")
    async def test_resolve_journals(self, mock_journal_service, mock_get_legal, mock_info):
        legal_entity_id = uuid4()
        mock_get_legal.return_value = legal_entity_id
        mock_service = AsyncMock()
        mock_service.list_journals_graphql.return_value = [
            {
                "id": uuid4(),
                "voucher_number": "V001",
                "journal_date": date(2024, 1, 1),
                "description": "Test",
                "status": "posted",
                "total_debit": Decimal("100"),
                "total_credit": Decimal("100"),
                "created_by": "admin",
                "created_at": datetime.now(),
                "lines": [],
            }
        ]
        mock_journal_service.return_value = mock_service

        result = await resolve_journals(
            root=None, info=mock_info, start_date=date(2024, 1, 1), end_date=date(2024, 1, 31), limit=10
        )
        assert len(result) == 1
        assert isinstance(result[0], Journal)
        mock_service.list_journals_graphql.assert_awaited_once_with(
            legal_entity_id, date(2024, 1, 1), date(2024, 1, 31), 10
        )

    # ---------- ledger_entries ----------
    @patch("adapters.primary_api.graphql_adapter_schema.get_current_legal_entity")
    @patch("adapters.primary_api.graphql_adapter_schema.LedgerService")
    async def test_resolve_ledger_entries(self, mock_ledger_service, mock_get_legal, mock_info):
        legal_entity_id = uuid4()
        mock_get_legal.return_value = legal_entity_id
        mock_service = AsyncMock()
        mock_service.get_ledger_entries_graphql.return_value = [
            {
                "id": uuid4(),
                "journal_id": uuid4(),
                "voucher_number": "V001",
                "account_code": "101",
                "account_name": "Cash",
                "posting_date": date(2024, 1, 1),
                "debit_amount": Decimal("100"),
                "credit_amount": Decimal("0"),
                "description": "Test",
            }
        ]
        mock_ledger_service.return_value = mock_service

        result = await resolve_ledger_entries(
            root=None, info=mock_info, account_code="101", start_date=date(2024, 1, 1), end_date=date(2024, 1, 31)
        )
        assert len(result) == 1
        assert isinstance(result[0], LedgerEntry)
        assert result[0].account_code == "101"
        mock_service.get_ledger_entries_graphql.assert_awaited_once_with(
            legal_entity_id, "101", date(2024, 1, 1), date(2024, 1, 31)
        )

    # ---------- trial_balance ----------
    @patch("adapters.primary_api.graphql_adapter_schema.get_current_legal_entity")
    @patch("adapters.primary_api.graphql_adapter_schema.LedgerService")
    async def test_resolve_trial_balance(self, mock_ledger_service, mock_get_legal, mock_info):
        legal_entity_id = uuid4()
        mock_get_legal.return_value = legal_entity_id
        mock_service = AsyncMock()
        mock_service.get_trial_balance_graphql.return_value = {
            "lines": [
                {
                    "account_code": "101",
                    "account_name": "Cash",
                    "opening_balance_debit": Decimal("0"),
                    "opening_balance_credit": Decimal("0"),
                    "movement_debit": Decimal("100"),
                    "movement_credit": Decimal("0"),
                    "closing_balance_debit": Decimal("100"),
                    "closing_balance_credit": Decimal("0"),
                }
            ],
            "total_debit": Decimal("100"),
            "total_credit": Decimal("0"),
            "is_balanced": False,
        }
        mock_ledger_service.return_value = mock_service

        result = await resolve_trial_balance(
            root=None, info=mock_info, as_of_date=date(2024, 1, 31)
        )
        assert isinstance(result, TrialBalance)
        assert result.as_of_date == date(2024, 1, 31)
        assert len(result.lines) == 1
        assert result.is_balanced is False
        mock_service.get_trial_balance_graphql.assert_awaited_once_with(
            legal_entity_id, date(2024, 1, 31)
        )

    # ---------- balance_sheet ----------
    @patch("adapters.primary_api.graphql_adapter_schema.get_current_legal_entity")
    @patch("adapters.primary_api.graphql_adapter_schema.LedgerService")
    async def test_resolve_balance_sheet(self, mock_ledger_service, mock_get_legal, mock_info):
        legal_entity_id = uuid4()
        mock_get_legal.return_value = legal_entity_id
        mock_service = AsyncMock()
        mock_service.get_balance_sheet_graphql.return_value = {
            "assets": {"lines": [], "total": Decimal("100")},
            "liabilities": {"lines": [], "total": Decimal("0")},
            "equity": {"lines": [], "total": Decimal("100")},
            "total_assets": Decimal("100"),
            "total_liabilities_equity": Decimal("100"),
        }
        mock_ledger_service.return_value = mock_service

        result = await resolve_balance_sheet(
            root=None, info=mock_info, as_of_date=date(2024, 1, 31)
        )
        assert isinstance(result, BalanceSheet)
        assert result.total_assets == Decimal("100")
        mock_service.get_balance_sheet_graphql.assert_awaited_once_with(
            legal_entity_id, date(2024, 1, 31)
        )

    # ---------- income_statement ----------
    @patch("adapters.primary_api.graphql_adapter_schema.get_current_legal_entity")
    @patch("adapters.primary_api.graphql_adapter_schema.LedgerService")
    async def test_resolve_income_statement(self, mock_ledger_service, mock_get_legal, mock_info):
        legal_entity_id = uuid4()
        mock_get_legal.return_value = legal_entity_id
        mock_service = AsyncMock()
        mock_service.get_income_statement_graphql.return_value = {
            "total_revenue": Decimal("5000"),
            "total_expenses": Decimal("3000"),
            "net_income": Decimal("2000"),
            "lines": [
                {
                    "account_code": "400",
                    "account_name": "Revenue",
                    "current_period": Decimal("5000"),
                    "year_to_date": Decimal("5000"),
                }
            ],
        }
        mock_ledger_service.return_value = mock_service

        result = await resolve_income_statement(
            root=None, info=mock_info, start_date=date(2024, 1, 1), end_date=date(2024, 1, 31)
        )
        assert isinstance(result, IncomeStatement)
        assert result.net_income == Decimal("2000")
        assert len(result.lines) == 1
        mock_service.get_income_statement_graphql.assert_awaited_once_with(
            legal_entity_id, date(2024, 1, 1), date(2024, 1, 31)
        )

    # ---------- aging_ar ----------
    @patch("adapters.primary_api.graphql_adapter_schema.get_current_legal_entity")
    @patch("adapters.primary_api.graphql_adapter_schema.ARService")
    async def test_resolve_aging_ar(self, mock_ar_service, mock_get_legal, mock_info):
        legal_entity_id = uuid4()
        mock_get_legal.return_value = legal_entity_id
        mock_service = AsyncMock()
        mock_service.get_aging_graphql.return_value = [
            {
                "customer_id": str(uuid4()),
                "customer_name": "Acme",
                "total_outstanding": Decimal("1000"),
                "buckets": [{"bucket_name": "0-30", "total_amount": Decimal("600"), "percentage": 60.0}],
            }
        ]
        mock_ar_service.return_value = mock_service

        result = await resolve_aging_ar(
            root=None, info=mock_info, as_of_date=date(2024, 1, 31), customer_id=uuid4()
        )
        assert len(result) == 1
        assert isinstance(result[0], AgingReport)
        assert result[0].customer_name == "Acme"
        mock_service.get_aging_graphql.assert_awaited_once_with(
            legal_entity_id, date(2024, 1, 31), mock_info.context["customer_id"]
        )

    # ---------- stock_card ----------
    @patch("adapters.primary_api.graphql_adapter_schema.get_current_legal_entity")
    @patch("adapters.primary_api.graphql_adapter_schema.InventoryService")
    async def test_resolve_stock_card(self, mock_inv_service, mock_get_legal, mock_info):
        legal_entity_id = uuid4()
        mock_get_legal.return_value = legal_entity_id
        item_id = uuid4()
        warehouse_id = uuid4()
        mock_service = AsyncMock()
        mock_service.get_stock_card_graphql.return_value = {
            "item_id": item_id,
            "item_code": "ITEM001",
            "item_name": "Widget",
            "opening_quantity": Decimal("0"),
            "closing_quantity": Decimal("10"),
            "entries": [
                {
                    "date": date(2024, 1, 1),
                    "reference": "PO-001",
                    "in_quantity": Decimal("10"),
                    "out_quantity": Decimal("0"),
                    "balance_quantity": Decimal("10"),
                    "unit_cost": Decimal("100"),
                    "balance_value": Decimal("1000"),
                }
            ],
        }
        mock_inv_service.return_value = mock_service

        result = await resolve_stock_card(
            root=None, info=mock_info,
            item_id=item_id,
            warehouse_id=warehouse_id,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert isinstance(result, StockCard)
        assert result.item_code == "ITEM001"
        assert len(result.entries) == 1
        mock_service.get_stock_card_graphql.assert_awaited_once_with(
            legal_entity_id, item_id, warehouse_id, date(2024, 1, 1), date(2024, 1, 31)
        )

    # ---------- fixed_assets ----------
    @patch("adapters.primary_api.graphql_adapter_schema.get_current_legal_entity")
    @patch("adapters.primary_api.graphql_adapter_schema.FixedAssetService")
    async def test_resolve_fixed_assets(self, mock_fa_service, mock_get_legal, mock_info):
        legal_entity_id = uuid4()
        mock_get_legal.return_value = legal_entity_id
        mock_service = AsyncMock()
        mock_service.get_asset_list_graphql.return_value = [
            {
                "id": uuid4(),
                "asset_code": "FA001",
                "asset_name": "Building",
                "acquisition_cost": Decimal("1000000"),
                "accumulated_depreciation": Decimal("100000"),
                "net_book_value": Decimal("900000"),
                "status": "Active",
            }
        ]
        mock_fa_service.return_value = mock_service

        result = await resolve_fixed_assets(
            root=None, info=mock_info, as_of_date=date(2024, 1, 31), category="Building"
        )
        assert len(result) == 1
        assert isinstance(result[0], FixedAsset)
        assert result[0].asset_code == "FA001"
        mock_service.get_asset_list_graphql.assert_awaited_once_with(
            legal_entity_id, date(2024, 1, 31), "Building"
        )


# ============================================================================
# get_graphql_context
# ============================================================================
async def test_get_graphql_context():
    request = MagicMock()
    result = await get_graphql_context(request)
    assert result == {"request": request}