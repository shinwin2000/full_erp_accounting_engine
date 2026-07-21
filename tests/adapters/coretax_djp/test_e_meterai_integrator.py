# tests/adapters/coretax_djp/test_e_meterai_integrator.py
# Perbaikan kualitas assertions: semua assert True dihapus,
# diganti dengan assertion yang memeriksa nilai aktual,
# efek samping, atau interaksi mock.
# Semua async test diberikan marker @pytest.mark.asyncio.
# Duplikasi dihilangkan dengan parametrize.
# Flaky tests diperbaiki dengan mock datetime.

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from uuid import UUID, uuid4

from adapters.coretax_djp.e_meterai_integrator import (
    CORETAX_EMETERAI_PURCHASE_ENDPOINT,
    CORETAX_EMETERAI_USE_ENDPOINT,
    CORETAX_EMETERAI_VALIDATE_ENDPOINT,
    EMETERAI_PATTERN,
    METERAI_THRESHOLD,
    METERRY_VALUE,
    EMeterai,
    EMeteraiAlreadyAttachedError,
    EMeteraiError,
    EMeteraiExpiredError,
    EMeteraiInsufficientStockError,
    EMeteraiIntegrator,
    EMeteraiInvalidError,
    EMeteraiLockedError,
    EMeteraiNotFoundError,
    EMeteraiRepositoryPort,
    EMeteraiStatus,
    EMeteraiUsedError,
    _FallbackEMeteraiRepository,
    get_e_meterai_integrator,
)

# ============================================================================
# FIXED DATETIME
# ============================================================================
FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0)
FIXED_TODAY = date(2026, 1, 1)
FIXED_EXPIRY = date(2026, 12, 31)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now() and date.today() to avoid flaky tests."""
    with patch("adapters.coretax_djp.e_meterai_integrator.datetime") as mock_dt, \
         patch("adapters.coretax_djp.e_meterai_integrator.date") as mock_date:
        mock_dt.now.return_value = FIXED_NOW
        mock_date.today.return_value = FIXED_TODAY
        yield mock_dt, mock_date


# ============================================================================
# Enum tests
# ============================================================================
class TestEMeteraiStatus:
    def test_members_exist(self):
        expected = [
            "ACTIVE",
            "USED",
            "EXPIRED",
            "REVOKED",
            "PENDING",
            "PURCHASED",
            "ALLOCATED",
            "VOID",
            "ARCHIVED",
            "LOCKED",
            "ERROR",
        ]
        for name in expected:
            assert hasattr(EMeteraiStatus, name)

    def test_member_is_instance(self):
        assert isinstance(EMeteraiStatus.ACTIVE, EMeteraiStatus)


# ============================================================================
# Custom exception classes - all parametrized
# ============================================================================
@pytest.mark.parametrize("exception_class", [
    EMeteraiError,
    EMeteraiNotFoundError,
    EMeteraiInvalidError,
    EMeteraiUsedError,
    EMeteraiExpiredError,
    EMeteraiInsufficientStockError,
    EMeteraiLockedError,
    EMeteraiAlreadyAttachedError,
])
class TestEMeteraiExceptions:
    def test_construction(self, exception_class):
        instance = exception_class()
        assert isinstance(instance, exception_class)
        assert isinstance(instance, Exception)


# ============================================================================
# Entity: EMeterai
# ============================================================================
class TestEMeterai:
    @pytest.fixture
    def meterai(self) -> EMeterai:
        return EMeterai(
            meterai_code="1234567890123456-0001",
            npwp="123456789012345",
            status=EMeteraiStatus.PENDING,
            value=METERRY_VALUE,
            purchased_at=FIXED_NOW,
            used_at=None,
            used_on_document=None,
            used_on_document_type=None,
            expiry_date=FIXED_EXPIRY,
            transaction_id=None,
            meterai_id=uuid4(),
            version=1,
        )

    def test_construction(self, meterai: EMeterai):
        assert isinstance(meterai, EMeterai)
        assert meterai.meterai_code == "1234567890123456-0001"
        assert meterai.npwp == "123456789012345"
        assert meterai.status == EMeteraiStatus.PENDING
        assert meterai.value == METERRY_VALUE
        assert meterai.version == 1

    def test_meterai_code_masked(self, meterai: EMeterai):
        assert meterai.meterai_code_masked == "12345678...0001"
        # jika pendek
        short = EMeterai(meterai_code="123", npwp="123")
        assert short.meterai_code_masked == "123"

    def test_properties_is_locked_is_active(self, meterai: EMeterai):
        assert not meterai.is_locked
        assert meterai.is_active is False  # status PENDING
        meterai._status = EMeteraiStatus.ACTIVE
        assert meterai.is_active is True
        meterai._locked_at = FIXED_NOW
        assert meterai.is_locked is True

    def test_is_expired_and_is_valid(self, meterai: EMeterai):
        meterai._status = EMeteraiStatus.ACTIVE
        meterai._expiry_date = FIXED_TODAY - timedelta(days=1)
        assert meterai.is_expired is True
        assert meterai.is_valid is False

        meterai._expiry_date = FIXED_TODAY + timedelta(days=1)
        assert meterai.is_expired is False
        assert meterai.is_valid is True

    def test_create_method(self, meterai: EMeterai):
        user = uuid4()
        result = meterai.create(user)
        assert result is meterai
        assert meterai.status == EMeteraiStatus.PENDING
        assert meterai.version == 2
        events = meterai.get_events()
        assert any(e["event_type"] == "e_meterai_created" for e in events)
        assert events[-1]["data"]["created_by"] == str(user)

    def test_update_method(self, meterai: EMeterai):
        user = uuid4()
        meterai._status = EMeteraiStatus.PENDING
        old_version = meterai.version
        data = {"npwp": "999", "value": "15000"}
        meterai.update(data, user)
        assert meterai.npwp == "999"
        assert meterai.value == Decimal("15000")
        assert meterai.version == old_version + 1
        events = meterai.get_events()
        assert any(e["event_type"] == "e_meterai_updated" for e in events)

    def test_update_locked_raises(self, meterai: EMeterai):
        meterai._locked_at = FIXED_NOW
        with pytest.raises(EMeteraiLockedError):
            meterai.update({}, uuid4())

    def test_delete_restore(self, meterai: EMeterai):
        user = uuid4()
        meterai.delete(user, permanent=False)
        assert meterai.status == EMeteraiStatus.ARCHIVED
        meterai.restore(user)
        assert meterai.status == EMeteraiStatus.PENDING

        meterai.delete(user, permanent=True)
        assert meterai.status == EMeteraiStatus.VOID

    def test_activate_deactivate(self, meterai: EMeterai):
        user = uuid4()
        meterai._status = EMeteraiStatus.PURCHASED
        meterai.activate(user)
        assert meterai.status == EMeteraiStatus.ACTIVE
        meterai.deactivate(user)
        assert meterai.status == EMeteraiStatus.PURCHASED

    def test_lock_unlock(self, meterai: EMeterai):
        user = uuid4()
        meterai.lock(user)
        assert meterai.is_locked is True
        assert meterai.locked_by == user
        assert meterai.status == EMeteraiStatus.LOCKED
        meterai.unlock(user)
        assert meterai.is_locked is False
        assert meterai.locked_by is None
        assert meterai.status == EMeteraiStatus.ACTIVE

    def test_validate(self, meterai: EMeterai):
        user = uuid4()
        # set agar valid
        meterai._status = EMeteraiStatus.PENDING
        meterai._expiry_date = FIXED_TODAY + timedelta(days=1)
        meterai.validate(user, "doc123")
        assert meterai.status == EMeteraiStatus.ACTIVE
        assert meterai.validated_at is not None

        # expired
        meterai._expiry_date = FIXED_TODAY - timedelta(days=1)
        with pytest.raises(EMeteraiExpiredError):
            meterai.validate(user)

    def test_use(self, meterai: EMeterai):
        user = uuid4()
        meterai._status = EMeteraiStatus.ACTIVE
        meterai._expiry_date = FIXED_TODAY + timedelta(days=1)
        meterai.use("doc1", "invoice", Decimal("6000000"), user)
        assert meterai.status == EMeteraiStatus.USED
        assert meterai.used_on_document == "doc1"
        assert meterai.used_on_document_type == "invoice"
        assert meterai.used_at is not None

        # document value below threshold
        with pytest.raises(EMeteraiError, match="below threshold"):
            meterai.use("doc2", "invoice", Decimal("1000"), user)

        # already used
        meterai._status = EMeteraiStatus.USED
        with pytest.raises(EMeteraiUsedError):
            meterai.use("doc3", "invoice", Decimal("6000000"), user)

    def test_purchase(self, meterai: EMeterai):
        user = uuid4()
        meterai.purchase(10, user, "txn123")
        assert meterai.status == EMeteraiStatus.PURCHASED
        assert meterai.transaction_id == "txn123"
        assert meterai.purchased_at is not None

    def test_revoke(self, meterai: EMeterai):
        user = uuid4()
        meterai._status = EMeteraiStatus.USED
        meterai.revoke(user, "test reason")
        assert meterai.status == EMeteraiStatus.REVOKED
        assert meterai.revoked_reason == "test reason"

    def test_get_status(self, meterai: EMeterai):
        status = meterai.get_status()
        assert status["meterai_code"] == meterai.meterai_code_masked
        assert status["status"] == "pending"
        assert status["is_valid"] is False

    def test_snapshot(self, meterai: EMeterai):
        snap = meterai.snapshot()
        assert snap["meterai_id"] == str(meterai.meterai_id)
        assert "meterai_code" in snap

    def test_to_dict_and_from_dict(self, meterai: EMeterai):
        d = meterai.to_dict()
        assert d["meterai_code"] == meterai.meterai_code
        new_meterai = EMeterai.from_dict(d)
        assert new_meterai.meterai_code == meterai.meterai_code
        assert new_meterai.npwp == meterai.npwp

    def test_transition(self, meterai: EMeterai):
        user = uuid4()
        meterai.transition(EMeteraiStatus.PURCHASED, user)
        assert meterai.status == EMeteraiStatus.PURCHASED
        history = meterai.get_history()
        assert len(history) == 1
        assert history[0]["from_status"] == "pending"

        with pytest.raises(EMeteraiError):
            meterai.transition(EMeteraiStatus.USED, user)  # tidak bisa langsung ke used

    def test_check_expiry(self, meterai: EMeterai):
        meterai._expiry_date = FIXED_TODAY - timedelta(days=1)
        meterai._status = EMeteraiStatus.ACTIVE
        assert meterai.check_expiry() is True
        assert meterai.status == EMeteraiStatus.EXPIRED
        events = meterai.get_events()
        assert any(e["event_type"] == "e_meterai_expired" for e in events)

    def test_clone(self, meterai: EMeterai):
        cloned = meterai.clone()
        assert cloned.meterai_code == meterai.meterai_code
        assert cloned.npwp == meterai.npwp
        assert cloned.status == EMeteraiStatus.PENDING
        assert cloned.meterai_id != meterai.meterai_id


# ============================================================================
# Repository interface (abstract) - di-skip
# ============================================================================
class TestEMeteraiRepositoryPort:
    @pytest.mark.skip(reason="Abstract interface, not meant to be instantiated.")
    def test_construction(self):
        pass


# ============================================================================
# Fallback in-memory repository
# ============================================================================
class Test_FallbackEMeteraiRepository:
    @pytest.fixture
    def repo(self) -> _FallbackEMeteraiRepository:
        return _FallbackEMeteraiRepository()

    @pytest.fixture
    def meterai(self) -> EMeterai:
        return EMeterai(
            meterai_code="1234567890123456-0001",
            npwp="123456789012345",
            status=EMeteraiStatus.PENDING,
            value=METERRY_VALUE,
        )

    @pytest.mark.asyncio
    async def test_add_and_get_by_id(self, repo: _FallbackEMeteraiRepository, meterai: EMeterai):
        await repo.add(meterai)
        stored = await repo.get_by_id(meterai.meterai_id)
        assert stored is meterai

    @pytest.mark.asyncio
    async def test_get_by_code(self, repo: _FallbackEMeteraiRepository, meterai: EMeterai):
        await repo.add(meterai)
        stored = await repo.get_by_code("1234567890123456-0001")
        assert stored is meterai
        assert await repo.get_by_code("invalid") is None

    @pytest.mark.asyncio
    async def test_get_by_npwp(self, repo: _FallbackEMeteraiRepository, meterai: EMeterai):
        await repo.add(meterai)
        results = await repo.get_by_npwp("123456789012345")
        assert len(results) == 1
        assert results[0] is meterai

        results_with_status = await repo.get_by_npwp("123456789012345", EMeteraiStatus.PENDING)
        assert len(results_with_status) == 1

        results_with_status2 = await repo.get_by_npwp("123456789012345", EMeteraiStatus.ACTIVE)
        assert len(results_with_status2) == 0

    @pytest.mark.asyncio
    async def test_get_stock_count(self, repo: _FallbackEMeteraiRepository, meterai: EMeterai):
        await repo.add(meterai)
        # status pending, not active, count should be 0
        count = await repo.get_stock_count("123456789012345")
        assert count == 0

        meterai._status = EMeteraiStatus.ACTIVE
        meterai._expiry_date = FIXED_EXPIRY
        await repo.update(meterai)
        count = await repo.get_stock_count("123456789012345")
        assert count == 1

    @pytest.mark.asyncio
    async def test_mark_as_used(self, repo: _FallbackEMeteraiRepository, meterai: EMeterai):
        await repo.add(meterai)
        meterai._status = EMeteraiStatus.ACTIVE
        meterai._expiry_date = FIXED_EXPIRY
        await repo.update(meterai)
        await repo.mark_as_used(meterai.meterai_id, "doc1", "invoice")
        updated = await repo.get_by_id(meterai.meterai_id)
        assert updated.status == EMeteraiStatus.USED
        assert updated.used_on_document == "doc1"


# ============================================================================
# Integrator
# ============================================================================
class TestEMeteraiIntegrator:
    @pytest.fixture
    def mock_repo(self) -> AsyncMock:
        return AsyncMock(spec=EMeteraiRepositoryPort)

    @pytest.fixture
    def integrator(self, mock_repo: AsyncMock) -> EMeteraiIntegrator:
        i = EMeteraiIntegrator(config={})
        i._repository = mock_repo
        return i

    @pytest.fixture
    def meterai(self) -> EMeterai:
        return EMeterai(
            meterai_code="1234567890123456-0001",
            npwp="123456789012345",
            status=EMeteraiStatus.PENDING,
            value=METERRY_VALUE,
        )

    # ------------------------------------------------------------------------
    # create
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_create_ok(self, integrator: EMeteraiIntegrator, mock_repo: AsyncMock):
        mock_repo.get_by_code.return_value = None
        mock_repo.add.return_value = None

        data = {
            "meterai_code": "1234567890123456-0001",
            "npwp": "123456789012345",
            "value": "10000",
        }
        result = await integrator.create(data, uuid4())
        assert result["success"] is True
        assert "meterai_id" in result
        assert result["status"] == "pending"
        mock_repo.add.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_invalid_format(self, integrator: EMeteraiIntegrator):
        data = {"meterai_code": "invalid", "npwp": "123"}
        result = await integrator.create(data, uuid4())
        assert result["success"] is False
        assert "Invalid" in result["error"]

    @pytest.mark.asyncio
    async def test_create_already_exists(self, integrator: EMeteraiIntegrator, mock_repo: AsyncMock, meterai: EMeterai):
        mock_repo.get_by_code.return_value = meterai
        data = {"meterai_code": "1234567890123456-0001", "npwp": "123"}
        result = await integrator.create(data, uuid4())
        assert result["success"] is False
        assert "already registered" in result["error"]

    # ------------------------------------------------------------------------
    # validate
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_validate_success(self, integrator: EMeteraiIntegrator, mock_repo: AsyncMock):
        mock_repo.get_by_code.return_value = None
        mock_repo.add.return_value = None
        mock_repo.update.return_value = None

        mock_client = AsyncMock()
        mock_client.post.return_value = {
            "isValid": True,
            "status": "active",
            "value": 10000,
            "message": "Valid",
            "npwp": "123456789012345",
        }

        with patch.object(integrator, "_get_coretax_client", return_value=mock_client):
            result = await integrator.validate("1234567890123456-0001", "doc1", "invoice", uuid4())

        assert result["success"] is True
        assert result["is_valid"] is True
        assert result["meterai_code"] == "12345678...0001"
        mock_client.post.assert_awaited_once_with(
            CORETAX_EMETERAI_VALIDATE_ENDPOINT,
            {
                "meterai_code": "1234567890123456-0001",
                "document_id": "doc1",
                "document_type": "invoice",
            }
        )
        mock_repo.add.assert_awaited_once()  # karena tidak ada existing

    @pytest.mark.asyncio
    async def test_validate_cache_hit(self, integrator: EMeteraiIntegrator):
        # pre-populate cache
        cache_key = integrator._get_cache_key("1234567890123456-0001")
        integrator._cache[cache_key] = {"success": True, "is_valid": True}

        result = await integrator.validate("1234567890123456-0001")
        assert result["success"] is True
        assert result["is_valid"] is True

    @pytest.mark.asyncio
    async def test_validate_invalid_format(self, integrator: EMeteraiIntegrator):
        result = await integrator.validate("invalid")
        assert result["success"] is False
        assert "Invalid" in result["error"]
        assert result["is_valid"] is False

    @pytest.mark.asyncio
    async def test_validate_already_used(self, integrator: EMeteraiIntegrator):
        mock_client = AsyncMock()
        mock_client.post.return_value = {
            "isValid": False,
            "status": "used",
            "document_id": "doc1",
            "message": "Already used",
        }

        with patch.object(integrator, "_get_coretax_client", return_value=mock_client):
            result = await integrator.validate("1234567890123456-0001")

        assert result["success"] is True
        assert result["is_valid"] is False
        assert "already used" in result["error"]

    # ------------------------------------------------------------------------
    # use
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_use_success(self, integrator: EMeteraiIntegrator, mock_repo: AsyncMock, meterai: EMeterai):
        mock_repo.get_by_code.return_value = meterai
        mock_repo.update.return_value = None
        # mock validate agar berhasil
        with patch.object(integrator, "validate", return_value={
            "success": True,
            "is_valid": True,
            "meterai_code": meterai.meterai_code_masked,
        }):
            mock_client = AsyncMock()
            mock_client.post.return_value = {"status": "success", "message": "OK"}
            with patch.object(integrator, "_get_coretax_client", return_value=mock_client):
                result = await integrator.use(
                    "1234567890123456-0001",
                    "doc1",
                    "invoice",
                    Decimal("6000000"),
                    uuid4()
                )

        assert result["success"] is True
        assert result["document_id"] == "doc1"
        assert meterai.status == EMeteraiStatus.USED
        mock_repo.update.assert_awaited_once_with(meterai)
        mock_client.post.assert_awaited_once_with(
            CORETAX_EMETERAI_USE_ENDPOINT,
            {
                "meterai_code": "1234567890123456-0001",
                "document_id": "doc1",
                "document_type": "invoice",
                "document_value": 6000000.0,
            }
        )

    @pytest.mark.asyncio
    async def test_use_below_threshold(self, integrator: EMeteraiIntegrator):
        with patch.object(integrator, "validate", return_value={"success": True, "is_valid": True}):
            result = await integrator.use("code", "doc1", "invoice", Decimal("1000"), uuid4())
        assert result["success"] is False
        assert "below threshold" in result["error"]

    @pytest.mark.asyncio
    async def test_use_invalid_meterai(self, integrator: EMeteraiIntegrator):
        with patch.object(integrator, "validate", return_value={"success": True, "is_valid": False}):
            result = await integrator.use("code", "doc1", "invoice", Decimal("6000000"), uuid4())
        assert result["success"] is False
        assert "invalid" in result["error"].lower()

    # ------------------------------------------------------------------------
    # purchase
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_purchase_success(self, integrator: EMeteraiIntegrator, mock_repo: AsyncMock):
        mock_repo.add.return_value = None
        mock_client = AsyncMock()
        mock_client.post.return_value = {
            "status": "success",
            "meterai_list": ["1234567890123456-0001", "1234567890123456-0002"],
            "transaction_id": "txn123",
        }

        with patch.object(integrator, "_get_coretax_client", return_value=mock_client):
            result = await integrator.purchase(2, "123456789012345", "invoice", uuid4())

        assert result["success"] is True
        assert result["quantity"] == 2
        assert result["total_amount"] == float(2 * METERRY_VALUE)
        assert len(result["meterai_list"]) == 2
        mock_repo.add.assert_awaited()  # dua kali
        mock_client.post.assert_awaited_once_with(
            CORETAX_EMETERAI_PURCHASE_ENDPOINT,
            {
                "quantity": 2,
                "npwp": "123456789012345",
                "purpose": "invoice",
                "value": float(METERRY_VALUE),
            }
        )

    @pytest.mark.asyncio
    async def test_purchase_failure(self, integrator: EMeteraiIntegrator):
        mock_client = AsyncMock()
        mock_client.post.return_value = {"status": "failed", "message": "Insufficient balance"}

        with patch.object(integrator, "_get_coretax_client", return_value=mock_client):
            result = await integrator.purchase(2, "123", "invoice", uuid4())
        assert result["success"] is False
        assert "Insufficient balance" in result["error"]

    # ------------------------------------------------------------------------
    # get_stock
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_get_stock_success(self, integrator: EMeteraiIntegrator):
        mock_client = AsyncMock()
        mock_client.get.return_value = {
            "available_quantity": 10,
            "used_quantity": 5,
            "expired_quantity": 2,
            "meterai_list": [],
        }

        with patch.object(integrator, "_get_coretax_client", return_value=mock_client):
            result = await integrator.get_stock("123456789012345")

        assert result["success"] is True
        assert result["available_quantity"] == 10
        assert result["used_quantity"] == 5
        assert result["expired_quantity"] == 2
        mock_client.get.assert_awaited_once_with("/api/v1/e-meterai/stock/123456789012345")

    # ------------------------------------------------------------------------
    # get_status
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_get_status_from_repo(self, integrator: EMeteraiIntegrator, mock_repo: AsyncMock, meterai: EMeterai):
        mock_repo.get_by_code.return_value = meterai
        result = await integrator.get_status("1234567890123456-0001")
        assert result["status"] == "pending"
        assert result["meterai_code"] == meterai.meterai_code_masked

    @pytest.mark.asyncio
    async def test_get_status_from_validate(self, integrator: EMeteraiIntegrator, mock_repo: AsyncMock):
        mock_repo.get_by_code.return_value = None
        with patch.object(integrator, "validate", return_value={
            "success": True,
            "is_valid": True,
            "meterai_code": "12345678...0001",
            "status": "active",
        }):
            result = await integrator.get_status("1234567890123456-0001")
        assert result["status"] == "active"
        assert result["meterai_code"] == "12345678...0001"

    # ------------------------------------------------------------------------
    # revoke
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_revoke_success(self, integrator: EMeteraiIntegrator, mock_repo: AsyncMock, meterai: EMeterai):
        mock_repo.get_by_code.return_value = meterai
        mock_repo.update.return_value = None
        mock_client = AsyncMock()
        mock_client.post.return_value = {"status": "success"}

        with patch.object(integrator, "_get_coretax_client", return_value=mock_client):
            result = await integrator.revoke("1234567890123456-0001", "test reason", uuid4())

        assert result["success"] is True
        assert result["revoked"] is True
        assert meterai.status == EMeteraiStatus.REVOKED
        assert meterai.revoked_reason == "test reason"
        mock_repo.update.assert_awaited_once_with(meterai)

    @pytest.mark.asyncio
    async def test_revoke_not_found(self, integrator: EMeteraiIntegrator, mock_repo: AsyncMock):
        mock_repo.get_by_code.return_value = None
        result = await integrator.revoke("code", "reason", uuid4())
        assert result["success"] is False
        assert "not found" in result["error"]

    # ------------------------------------------------------------------------
    # auto_purchase_if_low
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_auto_purchase_if_low_stock_insufficient(self, integrator: EMeteraiIntegrator):
        """Test that auto-purchase is triggered when stock is below threshold."""
        with patch.object(integrator, "get_stock", return_value={"available_quantity": 10}):
            with patch.object(integrator, "purchase", return_value={"success": True, "quantity": 100}) as mock_purchase:
                result = await integrator.auto_purchase_if_low("npwp", threshold=20, purchase_quantity=100)
                mock_purchase.assert_awaited_once_with(100, "npwp", "auto_replenish")
                assert result["success"] is True
                assert result["quantity"] == 100

    @pytest.mark.asyncio
    async def test_auto_purchase_if_low_stock_sufficient(self, integrator: EMeteraiIntegrator):
        """Test that auto-purchase is NOT triggered when stock is above threshold."""
        with patch.object(integrator, "get_stock", return_value={"available_quantity": 50}):
            result = await integrator.auto_purchase_if_low("npwp", threshold=20)
            assert result["success"] is True
            assert result["auto_purchased"] is False
            assert result["available_quantity"] == 50

    # ------------------------------------------------------------------------
    # attach_to_document (alias use)
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_attach_to_document(self, integrator: EMeteraiIntegrator):
        with patch.object(integrator, "use", return_value={"success": True}) as mock_use:
            result = await integrator.attach_to_document("code", "doc1", "invoice", Decimal("6000000"), uuid4())
        assert result["success"] is True
        mock_use.assert_awaited_once_with("code", "doc1", "invoice", Decimal("6000000"), uuid4())

    # ------------------------------------------------------------------------
    # snapshot, to_dict, audit_trail, can_transition, transition, etc.
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_snapshot(self, integrator: EMeteraiIntegrator, mock_repo: AsyncMock, meterai: EMeterai):
        mock_repo.get_by_code.return_value = meterai
        snap = await integrator.snapshot("1234567890123456-0001")
        assert snap["meterai_id"] == str(meterai.meterai_id)

    @pytest.mark.asyncio
    async def test_to_dict(self, integrator: EMeteraiIntegrator, mock_repo: AsyncMock, meterai: EMeterai):
        mock_repo.get_by_code.return_value = meterai
        d = await integrator.to_dict("1234567890123456-0001")
        assert d["meterai_code"] == meterai.meterai_code

    @pytest.mark.asyncio
    async def test_audit_trail(self, integrator: EMeteraiIntegrator, mock_repo: AsyncMock, meterai: EMeterai):
        mock_repo.get_by_code.return_value = meterai
        meterai._history.append({"event": "test"})
        result = await integrator.audit_trail("1234567890123456-0001")
        assert result["success"] is True
        assert len(result["audit_trail"]) == 1

    @pytest.mark.asyncio
    async def test_can_transition(self, integrator: EMeteraiIntegrator, mock_repo: AsyncMock, meterai: EMeterai):
        mock_repo.get_by_code.return_value = meterai
        result = await integrator.can_transition("1234567890123456-0001", "PURCHASED")
        assert result["success"] is True
        assert result["can_transition"] is True

        result2 = await integrator.can_transition("1234567890123456-0001", "USED")
        assert result2["success"] is True
        assert result2["can_transition"] is False

    @pytest.mark.asyncio
    async def test_transition(self, integrator: EMeteraiIntegrator, mock_repo: AsyncMock, meterai: EMeterai):
        mock_repo.get_by_code.return_value = meterai
        mock_repo.update.return_value = None
        result = await integrator.transition("1234567890123456-0001", "PURCHASED", uuid4())
        assert result["success"] is True
        assert result["new_status"] == "PURCHASED"
        assert meterai.status == EMeteraiStatus.PURCHASED

    @pytest.mark.asyncio
    async def test_version(self, integrator: EMeteraiIntegrator, mock_repo: AsyncMock, meterai: EMeterai):
        mock_repo.get_by_code.return_value = meterai
        # mock EMeterai.version property
        with patch.object(EMeterai, "version", new_callable=MagicMock, return_value=5):
            result = await integrator.version("1234567890123456-0001")
            assert result["success"] is True
            assert result["version"] == 5

    @pytest.mark.asyncio
    async def test_register_event_and_get_events(self, integrator: EMeteraiIntegrator, mock_repo: AsyncMock, meterai: EMeterai):
        mock_repo.get_by_code.return_value = meterai
        mock_repo.update.return_value = None
        result = await integrator.register_event("1234567890123456-0001", "test_event", {"key": "value"})
        assert result["success"] is True
        events = result["events"]
        assert any(e["event_type"] == "test_event" for e in events)

        get_result = await integrator.get_events("1234567890123456-0001")
        assert get_result["success"] is True
        assert len(get_result["events"]) > 0

        clear_result = await integrator.clear_events("1234567890123456-0001")
        assert clear_result["success"] is True
        assert clear_result["events_cleared"] is True

    # ------------------------------------------------------------------------
    # Batch operations
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_validate_batch(self, integrator: EMeteraiIntegrator):
        with patch.object(integrator, "validate", side_effect=[
            {"success": True, "is_valid": True},
            {"success": True, "is_valid": False},
        ]):
            results = await integrator.validate_batch(["code1", "code2"])
        assert len(results) == 2
        assert results[0]["is_valid"] is True
        assert results[1]["is_valid"] is False

    @pytest.mark.asyncio
    async def test_purchase_batch(self, integrator: EMeteraiIntegrator):
        purchases = [{"quantity": 2, "npwp": "npwp1"}, {"quantity": 3, "npwp": "npwp2"}]
        with patch.object(integrator, "purchase", side_effect=[
            {"success": True, "quantity": 2},
            {"success": True, "quantity": 3},
        ]):
            results = await integrator.purchase_batch(purchases, uuid4())
        assert len(results) == 2
        assert results[0]["quantity"] == 2

    @pytest.mark.asyncio
    async def test_sync_stock_all(self, integrator: EMeteraiIntegrator):
        with patch.object(integrator, "get_stock", side_effect=[
            {"success": True, "available_quantity": 10},
            {"success": True, "available_quantity": 20},
        ]):
            result = await integrator.sync_stock_all(["npwp1", "npwp2"])
        assert result["success"] is True
        assert result["results"]["npwp1"]["available_quantity"] == 10
        assert result["results"]["npwp2"]["available_quantity"] == 20

    # ------------------------------------------------------------------------
    # Legacy method terapkan
    # ------------------------------------------------------------------------
    def test_terapkan(self, integrator: EMeteraiIntegrator):
        doc = {"id": "doc1"}
        result = integrator.terapkan(doc)
        assert hasattr(result, "kode_unik")
        assert result.nominal == METERRY_VALUE
        assert result.status == "ACTIVE"
        # coba lagi dengan dokumen yang sama -> harus raise ValueError
        with pytest.raises(ValueError, match="sudah bermeterai"):
            integrator.terapkan(doc)


# ============================================================================
# Module-level getter
# ============================================================================
@pytest.mark.asyncio
async def test_get_e_meterai_integrator():
    integrator = await get_e_meterai_integrator(config={})
    assert isinstance(integrator, EMeteraiIntegrator)
    # panggil lagi, harus instance yang sama
    integrator2 = await get_e_meterai_integrator()
    assert integrator2 is integrator