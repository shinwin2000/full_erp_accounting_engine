# adapters/coretax_djp/test_ntpn_validator.py
"""
Comprehensive unit tests for NTPN Validator.

Covers:
- PaymentStatus, NTPNStatus enums
- All exception classes
- NTPN entity: properties, status transitions, validation, usage, locking, events, serialization
- _FallbackNTPNRepository: CRUD operations
- NTPNValidator: create, validate, validate_batch, get_payment_status, get_detail, get_history,
  snapshot, mark_as_used, cancel, clear_cache, health_check, rate limiting, caching (Redis mocked)
- Module-level functions: get_ntpn_validator, get_ntpn_validator_dep
- Coretax API client mocked, Redis mocked
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from adapters.coretax_djp.ntpn_validator import (
    NTPN,
    NTPNAlreadyUsedError,
    NTPNAmountMismatchError,
    NTPNExpiredError,
    NTPNInvalidFormatError,
    NTPNLockedError,
    NTPNNotFoundError,
    NTPNRateLimitError,
    NTPNStatus,
    NTPNValidationError,
    NTPNValidator,
    PaymentStatus,
    _FallbackNTPNRepository,
    get_ntpn_validator,
    get_ntpn_validator_dep,
)

# =============================================================================
# Helpers
# =============================================================================

def create_ntpn(
    number="1234567890123456",
    amount=Decimal("1000000"),
    payment_date=None,
    npwp="123456789012345",
    tax_type="500",
    status=NTPNStatus.PENDING,
):
    if payment_date is None:
        payment_date = date.today()
    return NTPN(
        ntpn=number,
        amount=amount,
        payment_date=payment_date,
        npwp=npwp,
        tax_type=tax_type,
        status=status,
        ntpn_id=uuid4(),
        version=1,
    )


# =============================================================================
# Tests for Enums
# =============================================================================

class TestPaymentStatus:
    def test_values(self):
        assert PaymentStatus.PENDING.value == "pending"
        assert PaymentStatus.SUCCESS.value == "success"
        assert PaymentStatus.FAILED.value == "failed"
        assert PaymentStatus.EXPIRED.value == "expired"
        assert PaymentStatus.CANCELLED.value == "cancelled"
        assert PaymentStatus.REFUNDED.value == "refunded"
        assert PaymentStatus.PARTIAL.value == "partial"


class TestNTPNStatus:
    def test_values(self):
        assert NTPNStatus.ACTIVE.value == "active"
        assert NTPNStatus.USED.value == "used"
        assert NTPNStatus.EXPIRED.value == "expired"
        assert NTPNStatus.CANCELLED.value == "cancelled"
        assert NTPNStatus.PENDING.value == "pending"
        assert NTPNStatus.VALIDATED.value == "validated"
        assert NTPNStatus.LOCKED.value == "locked"
        assert NTPNStatus.ARCHIVED.value == "archived"
        assert NTPNStatus.ERROR.value == "error"


# =============================================================================
# Tests for Exceptions
# =============================================================================

class TestExceptions:
    def test_inheritance(self):
        assert issubclass(NTPNInvalidFormatError, NTPNValidationError)
        assert issubclass(NTPNNotFoundError, NTPNValidationError)
        assert issubclass(NTPNRateLimitError, NTPNValidationError)
        assert issubclass(NTPNAlreadyUsedError, NTPNValidationError)
        assert issubclass(NTPNExpiredError, NTPNValidationError)
        assert issubclass(NTPNAmountMismatchError, NTPNValidationError)
        assert issubclass(NTPNLockedError, NTPNValidationError)

    def test_instantiation(self):
        e = NTPNValidationError("test")
        assert str(e) == "test"


# =============================================================================
# Tests for NTPN Entity
# =============================================================================

class TestNTPNEntity:
    def test_initialization(self):
        ntpn = create_ntpn()
        assert ntpn.ntpn == "1234567890123456"
        assert ntpn.npwp == "123456789012345"
        assert ntpn.amount == Decimal("1000000")
        assert ntpn.status == NTPNStatus.PENDING
        assert ntpn.ntpn_id is not None
        assert ntpn.version == 1
        assert ntpn.ntpn_masked == "12345678...3456"
        assert ntpn.is_active is True
        assert not ntpn.is_valid
        assert not ntpn.is_used
        assert not ntpn.is_locked

    def test_tax_type_description(self):
        ntpn = create_ntpn(tax_type="500")
        assert ntpn.tax_type_description == "PPN"
        ntpn2 = create_ntpn(tax_type="999")
        assert ntpn2.tax_type_description == "Unknown"

    def test_create(self):
        ntpn = create_ntpn()
        created_by = uuid4()
        ntpn.create(created_by)
        assert ntpn.status == NTPNStatus.PENDING
        assert ntpn.version == 2
        events = ntpn.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "ntpn_created"
        assert events[0]["data"]["created_by"] == str(created_by)

    def test_update(self):
        ntpn = create_ntpn(status=NTPNStatus.PENDING)
        updated_by = uuid4()
        ntpn.update({"amount": Decimal("2000000"), "tax_type": "100"}, updated_by)
        assert ntpn.amount == Decimal("2000000")
        assert ntpn.tax_type == "100"
        assert ntpn.version == 2
        events = ntpn.get_events()
        assert events[-1]["event_type"] == "ntpn_updated"

    def test_update_locked_raises(self):
        ntpn = create_ntpn()
        ntpn.lock(uuid4())
        with pytest.raises(NTPNLockedError, match="locked"):
            ntpn.update({}, uuid4())

    def test_delete(self):
        ntpn = create_ntpn()
        deleted_by = uuid4()
        ntpn.delete(deleted_by, permanent=False)
        assert ntpn.status == NTPNStatus.ARCHIVED
        ntpn.delete(deleted_by, permanent=True)
        assert ntpn.status == NTPNStatus.CANCELLED
        assert ntpn.cancelled_at is not None

    def test_delete_locked_raises(self):
        ntpn = create_ntpn()
        ntpn.lock(uuid4())
        with pytest.raises(NTPNLockedError, match="locked"):
            ntpn.delete(uuid4())

    def test_restore(self):
        ntpn = create_ntpn(status=NTPNStatus.ARCHIVED)
        ntpn.restore(uuid4())
        assert ntpn.status == NTPNStatus.PENDING

    def test_activate_deactivate(self):
        ntpn = create_ntpn(status=NTPNStatus.PENDING)
        ntpn.activate(uuid4())
        assert ntpn.status == NTPNStatus.ACTIVE
        ntpn.deactivate(uuid4())
        assert ntpn.status == NTPNStatus.PENDING

    def test_lock_unlock(self):
        ntpn = create_ntpn()
        locked_by = uuid4()
        ntpn.lock(locked_by, "audit")
        assert ntpn.is_locked
        assert ntpn.locked_by == locked_by
        ntpn.unlock(uuid4())
        assert not ntpn.is_locked

    def test_validate(self):
        ntpn = create_ntpn()
        ntpn.validate(uuid4(), Decimal("1000000"))
        assert ntpn.is_valid
        assert ntpn.status == NTPNStatus.VALIDATED
        assert ntpn.validated_at is not None

    def test_validate_amount_mismatch(self):
        ntpn = create_ntpn()
        with pytest.raises(NTPNAmountMismatchError, match="Amount mismatch"):
            ntpn.validate(uuid4(), Decimal("999999"))

    def test_validate_already_used(self):
        ntpn = create_ntpn(status=NTPNStatus.USED)
        with pytest.raises(NTPNAlreadyUsedError, match="already used"):
            ntpn.validate(uuid4())

    def test_validate_locked(self):
        ntpn = create_ntpn()
        ntpn.lock(uuid4())
        with pytest.raises(NTPNLockedError, match="locked"):
            ntpn.validate(uuid4())

    def test_mark_as_used(self):
        ntpn = create_ntpn(status=NTPNStatus.VALIDATED)
        ntpn.mark_as_used("faktur-001", uuid4())
        assert ntpn.is_used
        assert ntpn.status == NTPNStatus.USED
        assert ntpn.used_for == "faktur-001"

    def test_mark_as_used_invalid_status(self):
        ntpn = create_ntpn()
        with pytest.raises(NTPNValidationError, match="Cannot use"):
            ntpn.mark_as_used("faktur", uuid4())

    def test_cancel(self):
        ntpn = create_ntpn()
        ntpn.cancel(uuid4(), "test")
        assert ntpn.status == NTPNStatus.CANCELLED
        assert ntpn.cancelled_reason == "test"

    def test_cancel_already_used(self):
        ntpn = create_ntpn(status=NTPNStatus.USED)
        with pytest.raises(NTPNValidationError, match="Cannot cancel"):
            ntpn.cancel(uuid4(), "test")

    def test_cancel_locked(self):
        ntpn = create_ntpn()
        ntpn.lock(uuid4())
        with pytest.raises(NTPNLockedError, match="locked"):
            ntpn.cancel(uuid4(), "test")

    def test_get_payment_status(self):
        ntpn = create_ntpn(status=NTPNStatus.VALIDATED)
        assert ntpn.get_payment_status() == PaymentStatus.SUCCESS
        ntpn2 = create_ntpn(status=NTPNStatus.PENDING)
        assert ntpn2.get_payment_status() == PaymentStatus.PENDING
        ntpn3 = create_ntpn(status=NTPNStatus.CANCELLED)
        assert ntpn3.get_payment_status() == PaymentStatus.CANCELLED
        ntpn4 = create_ntpn(status=NTPNStatus.EXPIRED)
        assert ntpn4.get_payment_status() == PaymentStatus.EXPIRED
        ntpn5 = create_ntpn(status=NTPNStatus.ERROR)
        assert ntpn5.get_payment_status() == PaymentStatus.FAILED

    def test_get_status(self):
        ntpn = create_ntpn()
        status = ntpn.get_status()
        assert status["ntpn"] == ntpn.ntpn_masked
        assert status["status"] == "pending"
        assert status["amount"] == "1000000"

    def test_get_history(self):
        ntpn = create_ntpn()
        ntpn._history.append({"event": "test"})
        history = ntpn.get_history()
        assert len(history) == 1
        assert history[0]["event"] == "test"

    def test_snapshot(self):
        ntpn = create_ntpn()
        snap = ntpn.snapshot()
        assert snap["ntpn"] == ntpn.ntpn
        assert snap["amount"] == "1000000"
        assert snap["status"] == "pending"

    def test_to_dict_from_dict(self):
        ntpn = create_ntpn(number="9999999999999999")
        d = ntpn.to_dict()
        assert d["ntpn"] == "9999999999999999"
        ntpn2 = NTPN.from_dict(d)
        assert ntpn2.ntpn == "9999999999999999"
        assert ntpn2.amount == ntpn.amount
        assert ntpn2.payment_date == ntpn.payment_date

    def test_audit_trail(self):
        ntpn = create_ntpn()
        ntpn._history.append({"audit": "test"})
        trail = ntpn.audit_trail()
        assert trail == ntpn._history

    def test_can_transition(self):
        ntpn = create_ntpn(status=NTPNStatus.PENDING)
        assert ntpn.can_transition(NTPNStatus.ACTIVE) is True
        assert ntpn.can_transition(NTPNStatus.USED) is False

    def test_transition(self):
        ntpn = create_ntpn(status=NTPNStatus.PENDING)
        ntpn.transition(NTPNStatus.ACTIVE, uuid4(), "reason")
        assert ntpn.status == NTPNStatus.ACTIVE
        history = ntpn.get_history()
        assert len(history) == 1
        assert history[0]["from_status"] == "pending"
        assert history[0]["to_status"] == "active"

    def test_transition_invalid_raises(self):
        ntpn = create_ntpn(status=NTPNStatus.USED)
        with pytest.raises(NTPNValidationError, match="invalid"):
            ntpn.transition(NTPNStatus.ACTIVE, uuid4())

    def test_register_event_and_clear(self):
        ntpn = create_ntpn()
        ntpn.register_event("test_event", {"data": "test"})
        events = ntpn.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "test_event"
        ntpn.clear_events()
        assert len(ntpn.get_events()) == 0

    def test_check_expiry(self):
        ntpn = create_ntpn(payment_date=date.today() - timedelta(days=2))
        with patch.object(date, "today", return_value=date.today() + timedelta(days=1)):
            result = ntpn.check_expiry()
            assert result is True
            assert ntpn.status == NTPNStatus.EXPIRED
        # Already used should not expire
        ntpn2 = create_ntpn(payment_date=date.today() - timedelta(days=2), status=NTPNStatus.USED)
        with patch.object(date, "today", return_value=date.today() + timedelta(days=1)):
            result = ntpn2.check_expiry()
            assert result is False
            assert ntpn2.status == NTPNStatus.USED

    def test_validate_format(self):
        ntpn = create_ntpn(number="1234567890123456")
        assert ntpn._validate_format() is True
        with pytest.raises(NTPNInvalidFormatError, match="Invalid NTPN format"):
            create_ntpn(number="1234567")._validate_format()

    def test_set_validation_response(self):
        ntpn = create_ntpn()
        response = {"is_valid": True, "message": "ok"}
        ntpn.set_validation_response(response)
        assert ntpn.validation_response == response
        assert ntpn.is_valid


# =============================================================================
# Tests for _FallbackNTPNRepository
# =============================================================================

class TestFallbackNTPNRepository:
    @pytest.mark.asyncio
    async def test_add_and_get_by_id(self):
        repo = _FallbackNTPNRepository()
        ntpn = create_ntpn()
        await repo.add(ntpn)
        retrieved = await repo.get_by_id(ntpn.ntpn_id)
        assert retrieved is not None
        assert retrieved.ntpn_id == ntpn.ntpn_id

    @pytest.mark.asyncio
    async def test_get_by_ntpn(self):
        repo = _FallbackNTPNRepository()
        ntpn = create_ntpn(number="1111111111111111")
        await repo.add(ntpn)
        retrieved = await repo.get_by_ntpn("1111111111111111")
        assert retrieved.ntpn == "1111111111111111"

    @pytest.mark.asyncio
    async def test_update(self):
        repo = _FallbackNTPNRepository()
        ntpn = create_ntpn()
        await repo.add(ntpn)
        ntpn._status = NTPNStatus.ACTIVE
        await repo.update(ntpn)
        retrieved = await repo.get_by_id(ntpn.ntpn_id)
        assert retrieved.status == NTPNStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_delete(self):
        repo = _FallbackNTPNRepository()
        ntpn = create_ntpn()
        await repo.add(ntpn)
        await repo.delete(ntpn.ntpn_id)
        retrieved = await repo.get_by_id(ntpn.ntpn_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_get_by_npwp(self):
        repo = _FallbackNTPNRepository()
        ntpn1 = create_ntpn(npwp="111", number="1111111111111111")
        ntpn2 = create_ntpn(npwp="222", number="2222222222222222")
        await repo.add(ntpn1)
        await repo.add(ntpn2)
        results = await repo.get_by_npwp("111")
        assert len(results) == 1
        assert results[0].npwp == "111"

    @pytest.mark.asyncio
    async def test_get_by_period(self):
        repo = _FallbackNTPNRepository()
        ntpn1 = create_ntpn(payment_date=date(2025, 1, 1))
        ntpn2 = create_ntpn(payment_date=date(2025, 1, 2))
        ntpn3 = create_ntpn(payment_date=date(2025, 1, 3))
        await repo.add(ntpn1)
        await repo.add(ntpn2)
        await repo.add(ntpn3)
        results = await repo.get_by_period(date(2025, 1, 1), date(2025, 1, 2))
        assert len(results) == 2
        assert results[0].payment_date == date(2025, 1, 1)
        assert results[1].payment_date == date(2025, 1, 2)

    @pytest.mark.asyncio
    async def test_get_by_status(self):
        repo = _FallbackNTPNRepository()
        ntpn1 = create_ntpn(status=NTPNStatus.PENDING)
        ntpn2 = create_ntpn(status=NTPNStatus.ACTIVE)
        await repo.add(ntpn1)
        await repo.add(ntpn2)
        results = await repo.get_by_status(NTPNStatus.PENDING)
        assert len(results) == 1
        assert results[0].status == NTPNStatus.PENDING

    @pytest.mark.asyncio
    async def test_exists(self):
        repo = _FallbackNTPNRepository()
        ntpn = create_ntpn(number="1234567890123456")
        await repo.add(ntpn)
        assert await repo.exists("1234567890123456") is True
        assert await repo.exists("9999999999999999") is False

    @pytest.mark.asyncio
    async def test_mark_as_used(self):
        repo = _FallbackNTPNRepository()
        ntpn = create_ntpn(number="1111111111111111", status=NTPNStatus.VALIDATED)
        await repo.add(ntpn)
        await repo.mark_as_used("1111111111111111", "faktur-001")
        retrieved = await repo.get_by_ntpn("1111111111111111")
        assert retrieved.status == NTPNStatus.USED
        assert retrieved.used_for == "faktur-001"


# =============================================================================
# Tests for NTPNValidator
# =============================================================================

@pytest.fixture
def validator():
    return NTPNValidator(config={})


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()
    redis.delete = AsyncMock()
    redis.keys = AsyncMock(return_value=[])
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock()
    redis.pipeline = MagicMock()
    pipe = AsyncMock()
    pipe.incr = MagicMock()
    pipe.expire = MagicMock()
    pipe.execute = AsyncMock()
    redis.pipeline.return_value = pipe
    return redis


@pytest.fixture
def mock_coretax_client():
    client = AsyncMock()
    client.post = AsyncMock(return_value={
        "isValid": True,
        "message": "Valid",
        "taxpayer_id": "123456789012345",
        "tax_type": "500",
        "period": "2025-01",
        "payment_date": "2025-01-01",
        "payment_date_matched": True,
        "amount": 1000000,
        "amount_matched": True,
    })
    client.get = AsyncMock(return_value={
        "amount": 1000000,
        "payment_date": "2025-01-01",
        "taxpayer_id": "123456789012345",
        "tax_type": "500",
        "status": "success",
        "status_description": "Paid",
    })
    return client


class TestNTPNValidator:
    @pytest.mark.asyncio
    async def test_create(self, validator):
        created_by = uuid4()
        data = {
            "ntpn": "1234567890123456",
            "amount": "1000000",
            "payment_date": date.today(),
            "npwp": "123456789012345",
            "tax_type": "500",
        }
        result = await validator.create(data, created_by)
        assert result["success"] is True
        assert result["ntpn"] == "12345678...3456"
        assert result["status"] == "pending"
        ntpn = await validator.get_by_ntpn("1234567890123456")
        assert ntpn is not None

    @pytest.mark.asyncio
    async def test_validate_success(self, validator, mock_coretax_client):
        validator._coretax_client = mock_coretax_client
        # Ensure rate limit allows
        validator._rate_limit_cache = {}
        result = await validator.validate(
            ntpn="1234567890123456",
            amount=Decimal("1000000"),
            payment_date=date(2025, 1, 1),
            npwp="123456789012345",
            tax_type="500",
            validator_id=uuid4(),
        )
        assert result["success"] is True
        assert result["is_valid"] is True
        assert "Valid" in result["validation_message"]
        # Should be cached
        cached = await validator._get_cached(validator._get_cache_key("1234567890123456"))
        assert cached is not None

    @pytest.mark.asyncio
    async def test_validate_invalid_format(self, validator):
        result = await validator.validate(
            ntpn="1234567",
            amount=Decimal("1000"),
            payment_date=date.today(),
            npwp="123",
        )
        assert result["success"] is False
        assert "must be 16 digits" in result["error"]

    @pytest.mark.asyncio
    async def test_validate_rate_limit_exceeded(self, validator):
        # Simulate rate limit exceeded by making _check_rate_limit return False
        with patch.object(validator, "_check_rate_limit", return_value=False):
            with pytest.raises(NTPNRateLimitError, match="Rate limit exceeded"):
                await validator.validate(
                    ntpn="1234567890123456",
                    amount=Decimal("1000"),
                    payment_date=date.today(),
                    npwp="123",
                )

    @pytest.mark.asyncio
    async def test_validate_cached(self, validator, mock_coretax_client):
        validator._coretax_client = mock_coretax_client
        cache_key = validator._get_cache_key("1234567890123456")
        cached_result = {"success": True, "is_valid": True, "ntpn": "12345678...3456"}
        validator._cache[cache_key] = cached_result
        result = await validator.validate(
            ntpn="1234567890123456",
            amount=Decimal("1000"),
            payment_date=date.today(),
            npwp="123",
        )
        assert result == cached_result
        mock_coretax_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_api_error_retry(self, validator, mock_coretax_client):
        validator._coretax_client = mock_coretax_client
        # First attempt raises, second succeeds
        mock_coretax_client.post.side_effect = [
            Exception("API error"),
            {"isValid": True, "message": "ok"},
        ]
        result = await validator.validate(
            ntpn="1234567890123456",
            amount=Decimal("1000"),
            payment_date=date.today(),
            npwp="123",
        )
        # Since the first attempt fails, the second succeeds, we should get success.
        assert result["success"] is True
        assert result["is_valid"] is True
        assert mock_coretax_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_validate_api_auth_error_retry(self, validator, mock_coretax_client):
        from adapters.coretax_djp.api_oauth2_client import CoretaxAuthError
        validator._coretax_client = mock_coretax_client
        mock_coretax_client.post.side_effect = CoretaxAuthError("auth fail")
        result = await validator.validate(
            ntpn="1234567890123456",
            amount=Decimal("1000"),
            payment_date=date.today(),
            npwp="123",
        )
        assert result["success"] is False
        assert "Authentication failed" in result["error"]
        # MAX_RETRY_ATTEMPTS attempts
        assert mock_coretax_client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_validate_batch(self, validator, mock_coretax_client):
        validator._coretax_client = mock_coretax_client
        ntpn_list = [
            ("1234567890123456", Decimal("1000"), date.today(), "500"),
            ("1234567890123457", Decimal("2000"), date.today(), "500"),
        ]
        results = await validator.validate_batch(ntpn_list, npwp="123", validator_id=uuid4())
        assert len(results) == 2
        assert all(r["success"] for r in results)

    @pytest.mark.asyncio
    async def test_get_payment_status_from_repo(self, validator):
        ntpn = create_ntpn(number="1234567890123456", status=NTPNStatus.VALIDATED)
        await validator._repository.add(ntpn)
        result = await validator.get_payment_status("1234567890123456")
        assert result["success"] is True
        assert result["status"] == "validated"

    @pytest.mark.asyncio
    async def test_get_payment_status_from_api(self, validator, mock_coretax_client):
        validator._coretax_client = mock_coretax_client
        result = await validator.get_payment_status("1234567890123456")
        assert result["success"] is True
        assert result["exists"] is True
        assert result["amount"] == 1000000

    @pytest.mark.asyncio
    async def test_get_detail(self, validator, mock_coretax_client):
        validator._coretax_client = mock_coretax_client
        result = await validator.get_detail("1234567890123456")
        assert result["success"] is True
        assert result["amount"] == 1000000
        assert result["taxpayer_id"] == "123456789012345"

    @pytest.mark.asyncio
    async def test_get_history(self, validator):
        ntpn = create_ntpn(number="1234567890123456")
        ntpn._history.append({"event": "test"})
        await validator._repository.add(ntpn)
        result = await validator.get_history("1234567890123456")
        assert result["success"] is True
        assert len(result["history"]) == 1

    @pytest.mark.asyncio
    async def test_snapshot(self, validator):
        ntpn = create_ntpn(number="1234567890123456")
        await validator._repository.add(ntpn)
        result = await validator.snapshot("1234567890123456")
        assert result["ntpn"] == "1234567890123456"
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_mark_as_used(self, validator):
        ntpn = create_ntpn(number="1234567890123456", status=NTPNStatus.VALIDATED)
        await validator._repository.add(ntpn)
        result = await validator.mark_as_used("1234567890123456", "faktur-001", uuid4())
        assert result["success"] is True
        assert result["marked_as_used"] is True
        updated = await validator.get_by_ntpn("1234567890123456")
        assert updated.status == NTPNStatus.USED

    @pytest.mark.asyncio
    async def test_cancel(self, validator):
        ntpn = create_ntpn(number="1234567890123456")
        await validator._repository.add(ntpn)
        result = await validator.cancel("1234567890123456", uuid4(), "test")
        assert result["success"] is True
        assert result["cancelled"] is True
        updated = await validator.get_by_ntpn("1234567890123456")
        assert updated.status == NTPNStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_clear_cache_specific(self, validator):
        cache_key = validator._get_cache_key("1234567890123456")
        validator._cache[cache_key] = {"test": "value"}
        await validator.clear_cache("1234567890123456")
        assert cache_key not in validator._cache

    @pytest.mark.asyncio
    async def test_clear_cache_all(self, validator):
        validator._cache = {"a": 1, "b": 2}
        await validator.clear_cache()
        assert validator._cache == {}

    @pytest.mark.asyncio
    async def test_health_check(self, validator, mock_coretax_client):
        validator._coretax_client = mock_coretax_client
        result = await validator.health_check(
            ntpn="1234567890123456",
            amount=Decimal("1000"),
            payment_date=date.today(),
            npwp="123",
        )
        assert result["success"] is True
        assert result["ntpn_validator_status"] == "healthy"
        assert result["api_reachable"] is True

    def test_get_tax_type_description(self, validator):
        assert validator.get_tax_type_description("500") == "PPN"
        assert validator.get_tax_type_description("999") == "Unknown"

    # Legacy sync method
    def test_validate_sync(self, validator):
        validator._test_valid_ntpns = {"1234567890123456"}
        assert validator.validate_sync("1234567890123456") is True
        with pytest.raises(ValueError, match="NTPN tidak terdaftar"):
            validator.validate_sync("9999999999999999")

    # Rate limiting test with Redis
    @pytest.mark.asyncio
    async def test_check_rate_limit_redis(self, validator, mock_redis):
        validator._redis_client = mock_redis
        # First call should return True
        result = await validator._check_rate_limit("123")
        assert result is True
        mock_redis.get.assert_called_once()
        mock_redis.incr.assert_called_once()
        mock_redis.expire.assert_called_once()

        # Simulate rate limit exceeded
        mock_redis.get = AsyncMock(return_value=b"10")  # limit is 10
        result2 = await validator._check_rate_limit("123")
        assert result2 is False

    # Rate limiting without Redis
    @pytest.mark.asyncio
    async def test_check_rate_limit_fallback(self, validator):
        validator._redis_client = None
        validator._rate_limit_cache = {}
        # Should allow up to limit calls
        for _i in range(10):
            result = await validator._check_rate_limit("123")
            assert result is True
        # 11th call should fail
        result_last = await validator._check_rate_limit("123")
        assert result_last is False
        # After period, should allow again (but we can't simulate time easily; we'll just check count)
        # We'll just verify the cache has the timestamps.
        assert len(validator._rate_limit_cache["123"]) == 10


# =============================================================================
# Tests for Module-level Functions
# =============================================================================

@patch("adapters.coretax_djp.ntpn_validator.NTPNValidator")
async def test_get_ntpn_validator(mock_validator_class):
    instance = AsyncMock()
    mock_validator_class.return_value = instance
    import adapters.coretax_djp.ntpn_validator as mod
    mod._ntpn_validator = None
    result = await get_ntpn_validator(config={"test": True})
    assert result is instance
    mock_validator_class.assert_called_once_with(config={"test": True})

@patch("adapters.coretax_djp.ntpn_validator.get_ntpn_validator")
async def test_get_ntpn_validator_dep(mock_get):
    mock_get.return_value = "validator"
    result = await get_ntpn_validator_dep()
    assert result == "validator"
