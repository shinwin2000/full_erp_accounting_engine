# tests/adapters/secondary_impl/test_sqlalchemy_umkm_repository_impl.py
"""
Comprehensive tests for adapters/secondary_impl/sqlalchemy_umkm_repository_impl.py
Covers all public, private, and internal methods with proper mocking.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from adapters.secondary_impl.sqlalchemy_umkm_repository_impl import SQLAlchemyUMKMRepository
from infrastructure.persistence_orm.umkm_business_profile_table import UMKMProfileTable
from infrastructure.persistence_orm.umkm_transaction_table import UMKMTransactionTable
from ports.primary.umkm_repository_port import UMKMRevenueSummary, UMKMTransactionEntity

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_session():
    session = AsyncMock(spec=AsyncSession)
    session.begin = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.get = AsyncMock()
    return session


@pytest.fixture
def legal_entity_id():
    return uuid.uuid4()


@pytest.fixture
def profile_id():
    return uuid.uuid4()


@pytest.fixture
def repo(mock_session, legal_entity_id):
    return SQLAlchemyUMKMRepository(session=mock_session, legal_entity_id=legal_entity_id)


@pytest.fixture
def sample_transaction_entity(legal_entity_id):
    return UMKMTransactionEntity(
        id=uuid.uuid4(),
        legal_entity_id=legal_entity_id,
        transaction_date=date(2026, 1, 15),
        description="Test transaction",
        amount=Decimal("1000000"),
        transaction_type="revenue",
        category="Sales",
        payment_method="Cash",
        reference_number="REF-001",
        attachment_ids=[],
        created_by=uuid.uuid4(),
        created_at=datetime.utcnow(),
    )


@pytest.fixture
def sample_profile_row(profile_id, legal_entity_id):
    row = MagicMock(spec=UMKMProfileTable)
    row.id = profile_id
    row.legal_entity_id = legal_entity_id
    row.business_name = "Test Business"
    row.owner_name = "Owner"
    row.npwp = "123456789012345"
    row.uses_umkm_tax = True
    row.created_at = datetime.utcnow()
    row.updated_at = None
    return row


@pytest.fixture
def sample_transaction_row(sample_transaction_entity, profile_id):
    row = MagicMock(spec=UMKMTransactionTable)
    row.id = sample_transaction_entity.id
    row.profile_id = profile_id
    row.legal_entity_id = sample_transaction_entity.legal_entity_id
    row.transaction_date = sample_transaction_entity.transaction_date
    row.description = sample_transaction_entity.description
    row.amount = sample_transaction_entity.amount
    row.transaction_type = sample_transaction_entity.transaction_type
    row.category = sample_transaction_entity.category
    row.payment_method = sample_transaction_entity.payment_method
    row.reference_number = sample_transaction_entity.reference_number
    row.created_by = sample_transaction_entity.created_by
    row.created_at = sample_transaction_entity.created_at
    row.updated_at = None
    return row


# ============================================================================
# Tests for repository initialization and helpers
# ============================================================================

class TestSQLAlchemyUMKMRepositoryInit:
    def test_construction_with_session_and_legal_entity(self, mock_session, legal_entity_id):
        repo = SQLAlchemyUMKMRepository(session=mock_session, legal_entity_id=legal_entity_id)
        assert repo._session is mock_session
        assert repo._legal_entity_id == legal_entity_id

    def test_construction_without_session(self, legal_entity_id):
        repo = SQLAlchemyUMKMRepository(legal_entity_id=legal_entity_id)
        assert repo._session is None
        assert repo._legal_entity_id == legal_entity_id

    @pytest.mark.asyncio
    async def test_get_session_initializes(self, repo):
        with patch("adapters.secondary_impl.sqlalchemy_umkm_repository_impl.get_async_session") as mock_get:
            mock_session = AsyncMock()
            mock_get.return_value = mock_session
            session = await repo._get_session()
            assert session is mock_session
            assert repo._session is mock_session

    def test_get_legal_entity_id_success(self, repo, legal_entity_id):
        result = repo._get_legal_entity_id()
        assert result == legal_entity_id

    def test_get_legal_entity_id_raises_if_none(self):
        repo = SQLAlchemyUMKMRepository()
        with pytest.raises(ValueError, match="legal_entity_id not set"):
            repo._get_legal_entity_id()


# ============================================================================
# Tests for mapping methods
# ============================================================================

class TestMappingMethods:
    @pytest.fixture
    def repo(self):
        return SQLAlchemyUMKMRepository(session=MagicMock(), legal_entity_id=uuid.uuid4())

    def test_to_domain_transaction(self, repo, sample_transaction_row, sample_transaction_entity):
        result = repo._to_domain_transaction(sample_transaction_row)
        assert isinstance(result, UMKMTransactionEntity)
        assert result.id == sample_transaction_entity.id
        assert result.legal_entity_id == sample_transaction_entity.legal_entity_id
        assert result.transaction_date == sample_transaction_entity.transaction_date
        assert result.description == sample_transaction_entity.description
        assert result.amount == sample_transaction_entity.amount
        assert result.transaction_type == sample_transaction_entity.transaction_type
        assert result.category == sample_transaction_entity.category
        assert result.payment_method == sample_transaction_entity.payment_method
        assert result.reference_number == sample_transaction_entity.reference_number
        assert result.attachment_ids == []
        assert result.created_by == sample_transaction_entity.created_by
        assert result.created_at == sample_transaction_entity.created_at

    def test_from_domain_transaction(self, repo, sample_transaction_entity, profile_id):
        result = repo._from_domain_transaction(sample_transaction_entity, profile_id)
        assert isinstance(result, UMKMTransactionTable)
        assert result.id == sample_transaction_entity.id
        assert result.profile_id == profile_id
        assert result.transaction_date == sample_transaction_entity.transaction_date
        assert result.description == sample_transaction_entity.description
        assert result.amount == sample_transaction_entity.amount
        assert result.transaction_type == sample_transaction_entity.transaction_type
        assert result.category == sample_transaction_entity.category
        assert result.payment_method == sample_transaction_entity.payment_method
        assert result.reference_number == sample_transaction_entity.reference_number
        assert result.legal_entity_id == sample_transaction_entity.legal_entity_id
        assert result.created_by == sample_transaction_entity.created_by
        assert result.created_at is not None

    def test_to_domain_summary(self, repo, legal_entity_id):
        revenue = Decimal("10000000")
        expense = Decimal("3000000")
        year = 2026
        month = 5
        result = repo._to_domain_summary(legal_entity_id, year, month, revenue, expense)
        assert isinstance(result, UMKMRevenueSummary)
        assert result.legal_entity_id == legal_entity_id
        assert result.year == year
        assert result.month == month
        assert result.total_revenue == revenue
        assert result.total_expenses == expense
        assert result.net_income == revenue - expense
        assert result.pph_final_due == revenue * Decimal("0.005")
        assert result.pph_paid == Decimal(0)
        assert result.status == "DRAFT"
        assert result.submitted_at is None

    def test_to_domain_summary_zero_amounts(self, repo, legal_entity_id):
        result = repo._to_domain_summary(legal_entity_id, 2026, 1, Decimal(0), Decimal(0))
        assert result.net_income == Decimal(0)
        assert result.pph_final_due == Decimal(0)


# ============================================================================
# Tests for public repository methods
# ============================================================================

class TestPublicMethods:
    @pytest.mark.asyncio
    async def test_save_transaction_insert(self, repo, mock_session, sample_transaction_entity, profile_id):
        # Mock get profile id
        with patch.object(repo, '_get_profile_id', new_callable=AsyncMock) as mock_get_profile:
            mock_get_profile.return_value = profile_id
            # Mock session.get to return None (no existing)
            mock_session.get.return_value = None

            await repo.save_transaction(sample_transaction_entity)

            # Check that profile_id was fetched
            mock_get_profile.assert_called_once_with(sample_transaction_entity.legal_entity_id)
            # Check that session.add was called
            mock_session.add.assert_called_once()
            args, _ = mock_session.add.call_args
            added_obj = args[0]
            assert isinstance(added_obj, UMKMTransactionTable)
            assert added_obj.id == sample_transaction_entity.id
            assert added_obj.profile_id == profile_id
            # Check flush
            mock_session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_save_transaction_update(self, repo, mock_session, sample_transaction_entity, profile_id):
        with patch.object(repo, '_get_profile_id', new_callable=AsyncMock) as mock_get_profile:
            mock_get_profile.return_value = profile_id
            # Mock existing row
            existing_row = MagicMock(spec=UMKMTransactionTable)
            existing_row.id = sample_transaction_entity.id
            mock_session.get.return_value = existing_row

            # Change some fields
            sample_transaction_entity.description = "Updated description"
            sample_transaction_entity.amount = Decimal("2000000")

            await repo.save_transaction(sample_transaction_entity)

            # Check that existing row was updated
            assert existing_row.description == "Updated description"
            assert existing_row.amount == Decimal("2000000")
            assert existing_row.updated_at is not None
            # Check that add was not called (update path)
            mock_session.add.assert_not_called()
            mock_session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_save_transaction_profile_not_found(self, repo, sample_transaction_entity):
        with patch.object(repo, '_get_profile_id', new_callable=AsyncMock) as mock_get_profile:
            mock_get_profile.return_value = None
            with pytest.raises(ValueError, match="UMKM profile not found"):
                await repo.save_transaction(sample_transaction_entity)

    @pytest.mark.asyncio
    async def test_get_transaction_found(self, repo, mock_session, sample_transaction_row):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=sample_transaction_row)
        mock_session.execute.return_value = mock_result

        result = await repo.get_transaction(sample_transaction_row.id)

        assert result is not None
        assert result.id == sample_transaction_row.id
        assert result.description == sample_transaction_row.description
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_transaction_not_found(self, repo, mock_session):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=None)
        mock_session.execute.return_value = mock_result

        result = await repo.get_transaction(uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_list_transactions_by_period(self, repo, mock_session, sample_transaction_row, legal_entity_id, profile_id):
        with patch.object(repo, '_get_profile_id', new_callable=AsyncMock) as mock_get_profile:
            mock_get_profile.return_value = profile_id
            mock_result = AsyncMock()
            mock_result.scalars.return_value.all = MagicMock(return_value=[sample_transaction_row])
            mock_session.execute.return_value = mock_result

            from_date = date(2026, 1, 1)
            to_date = date(2026, 1, 31)
            results = await repo.list_transactions_by_period(legal_entity_id, from_date, to_date)

            assert len(results) == 1
            assert isinstance(results[0], UMKMTransactionEntity)
            assert results[0].id == sample_transaction_row.id
            mock_get_profile.assert_called_once_with(legal_entity_id)

    @pytest.mark.asyncio
    async def test_list_transactions_by_period_with_type_filter(self, repo, mock_session, sample_transaction_row, legal_entity_id, profile_id):
        with patch.object(repo, '_get_profile_id', new_callable=AsyncMock) as mock_get_profile:
            mock_get_profile.return_value = profile_id
            mock_result = AsyncMock()
            mock_result.scalars.return_value.all = MagicMock(return_value=[sample_transaction_row])
            mock_session.execute.return_value = mock_result

            from_date = date(2026, 1, 1)
            to_date = date(2026, 1, 31)
            results = await repo.list_transactions_by_period(legal_entity_id, from_date, to_date, transaction_type="revenue")
            assert len(results) == 1

    @pytest.mark.asyncio
    async def test_list_transactions_by_period_profile_not_found(self, repo, legal_entity_id):
        with patch.object(repo, '_get_profile_id', new_callable=AsyncMock) as mock_get_profile:
            mock_get_profile.return_value = None
            results = await repo.list_transactions_by_period(legal_entity_id, date.today(), date.today())
            assert results == []

    @pytest.mark.asyncio
    async def test_get_monthly_revenue_summary_success(self, repo, mock_session, legal_entity_id, profile_id):
        with patch.object(repo, '_get_profile_id', new_callable=AsyncMock) as mock_get_profile:
            mock_get_profile.return_value = profile_id
            # Mock revenue sum
            mock_rev_result = AsyncMock()
            mock_rev_result.scalar.return_value = Decimal("10000000")
            # Mock expense sum
            mock_exp_result = AsyncMock()
            mock_exp_result.scalar.return_value = Decimal("3000000")

            # Side effect: first call for profile, second for revenue, third for expense
            mock_session.execute.side_effect = [
                AsyncMock(scalar_one_or_none=AsyncMock(return_value=profile_id)),  # profile id query
                mock_rev_result,
                mock_exp_result,
            ]

            summary = await repo.get_monthly_revenue_summary(legal_entity_id, 2026, 5)
            assert summary is not None
            assert summary.total_revenue == Decimal("10000000")
            assert summary.total_expenses == Decimal("3000000")
            assert summary.net_income == Decimal("7000000")

    @pytest.mark.asyncio
    async def test_get_monthly_revenue_summary_profile_not_found(self, repo, legal_entity_id):
        with patch.object(repo, '_get_profile_id', new_callable=AsyncMock) as mock_get_profile:
            mock_get_profile.return_value = None
            summary = await repo.get_monthly_revenue_summary(legal_entity_id, 2026, 5)
            assert summary is None

    @pytest.mark.asyncio
    async def test_save_revenue_summary_logs(self, repo, legal_entity_id, caplog):
        summary = UMKMRevenueSummary(
            id=uuid.uuid4(),
            legal_entity_id=legal_entity_id,
            year=2026,
            month=5,
            total_revenue=Decimal("10000000"),
            total_expenses=Decimal("3000000"),
            net_income=Decimal("7000000"),
            pph_final_due=Decimal("50000"),
            pph_paid=Decimal(0),
            status="DRAFT",
            submitted_at=None,
        )
        with caplog.at_level("INFO"):
            await repo.save_revenue_summary(summary)
            assert "Saving revenue summary for 2026-5: net_income=7000000" in caplog.text

    @pytest.mark.asyncio
    async def test_submit_tax_report_logs(self, repo, legal_entity_id, caplog):
        user_id = uuid.uuid4()
        with caplog.at_level("INFO"):
            await repo.submit_tax_report(legal_entity_id, 2026, 5, user_id)
            assert f"Submitting tax report for 2026-5 by {user_id} for legal_entity {legal_entity_id}" in caplog.text

    @pytest.mark.asyncio
    async def test_get_total_revenue_ytd_success(self, repo, mock_session, legal_entity_id, profile_id):
        with patch.object(repo, '_get_profile_id', new_callable=AsyncMock) as mock_get_profile:
            mock_get_profile.return_value = profile_id
            mock_result = AsyncMock()
            mock_result.scalar.return_value = Decimal("50000000")
            mock_session.execute.return_value = mock_result

            revenue = await repo.get_total_revenue_ytd(legal_entity_id, 2026)
            assert revenue == Decimal("50000000")

    @pytest.mark.asyncio
    async def test_get_total_revenue_ytd_profile_not_found(self, repo, legal_entity_id):
        with patch.object(repo, '_get_profile_id', new_callable=AsyncMock) as mock_get_profile:
            mock_get_profile.return_value = None
            revenue = await repo.get_total_revenue_ytd(legal_entity_id, 2026)
            assert revenue == Decimal(0)


# ============================================================================
# Tests for internal/legacy methods
# ============================================================================

class TestInternalMethods:
    @pytest.mark.asyncio
    async def test_save_profile(self, repo, mock_session, sample_profile_row):
        await repo.save_profile(sample_profile_row)
        mock_session.add.assert_called_once_with(sample_profile_row)
        mock_session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_profile_by_id_found(self, repo, mock_session, sample_profile_row):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=sample_profile_row)
        mock_session.execute.return_value = mock_result

        result = await repo.get_profile_by_id(sample_profile_row.id)
        assert result is sample_profile_row

    @pytest.mark.asyncio
    async def test_get_profile_by_id_not_found(self, repo, mock_session):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=None)
        mock_session.execute.return_value = mock_result

        result = await repo.get_profile_by_id(uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_profile_by_legal_entity_found(self, repo, mock_session, sample_profile_row, legal_entity_id):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=sample_profile_row)
        mock_session.execute.return_value = mock_result

        result = await repo.get_profile_by_legal_entity(legal_entity_id)
        assert result is sample_profile_row

    @pytest.mark.asyncio
    async def test_get_profile_by_legal_entity_not_found(self, repo, mock_session):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=None)
        mock_session.execute.return_value = mock_result

        result = await repo.get_profile_by_legal_entity(uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_update_profile_tax_status_success(self, repo, mock_session, profile_id, sample_profile_row):
        # Mock lock select
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=sample_profile_row)
        mock_session.execute.return_value = mock_result

        await repo.update_profile_tax_status(profile_id, True)
        assert sample_profile_row.uses_umkm_tax is True
        mock_session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_profile_tax_status_profile_not_found(self, repo, mock_session, profile_id):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=None)
        mock_session.execute.return_value = mock_result

        with pytest.raises(ValueError, match="UMKM profile.*not found"):
            await repo.update_profile_tax_status(profile_id, True)

    @pytest.mark.asyncio
    async def test_get_transaction_by_id_found(self, repo, mock_session, sample_transaction_row):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=sample_transaction_row)
        mock_session.execute.return_value = mock_result

        result = await repo.get_transaction_by_id(sample_transaction_row.id)
        assert result is sample_transaction_row

    @pytest.mark.asyncio
    async def test_get_transactions_by_period(self, repo, mock_session, sample_transaction_row, profile_id):
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all = MagicMock(return_value=[sample_transaction_row])
        mock_session.execute.return_value = mock_result

        from_date = date(2026, 1, 1)
        to_date = date(2026, 1, 31)
        results = await repo.get_transactions_by_period(profile_id, from_date, to_date)
        assert len(results) == 1
        assert results[0] is sample_transaction_row

    @pytest.mark.asyncio
    async def test_get_total_revenue_by_period(self, repo, mock_session, profile_id):
        amounts = [Decimal("100"), Decimal("200"), Decimal("50")]
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all = MagicMock(return_value=amounts)
        mock_session.execute.return_value = mock_result

        from_date = date(2026, 1, 1)
        to_date = date(2026, 1, 31)
        total = await repo.get_total_revenue_by_period(profile_id, from_date, to_date)
        assert total == Decimal("350")

    @pytest.mark.asyncio
    async def test_get_total_revenue_by_period_empty(self, repo, mock_session, profile_id):
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all = MagicMock(return_value=[])
        mock_session.execute.return_value = mock_result

        total = await repo.get_total_revenue_by_period(profile_id, date.today(), date.today())
        assert total == Decimal(0)

    @pytest.mark.asyncio
    async def test_get_monthly_summary(self, repo, mock_session, profile_id):
        # Mock get_total_revenue_by_period
        with patch.object(repo, 'get_total_revenue_by_period', new_callable=AsyncMock) as mock_rev:
            mock_rev.return_value = Decimal("10000000")
            # Mock expense sum
            amounts = [Decimal("2000000"), Decimal("1000000")]
            mock_result = AsyncMock()
            mock_result.scalars.return_value.all = MagicMock(return_value=amounts)
            mock_session.execute.return_value = mock_result

            summary = await repo.get_monthly_summary(profile_id, 2026, 5)
            assert summary["revenue"] == Decimal("10000000")
            assert summary["expense"] == Decimal("3000000")
            assert summary["net"] == Decimal("7000000")
            mock_rev.assert_called_once_with(profile_id, date(2026, 5, 1), date(2026, 5, 31))

    @pytest.mark.asyncio
    async def test_get_monthly_summary_expense_empty(self, repo, mock_session, profile_id):
        with patch.object(repo, 'get_total_revenue_by_period', new_callable=AsyncMock) as mock_rev:
            mock_rev.return_value = Decimal("10000000")
            mock_result = AsyncMock()
            mock_result.scalars.return_value.all = MagicMock(return_value=[])
            mock_session.execute.return_value = mock_result

            summary = await repo.get_monthly_summary(profile_id, 2026, 5)
            assert summary["expense"] == Decimal(0)
            assert summary["net"] == Decimal("10000000")
