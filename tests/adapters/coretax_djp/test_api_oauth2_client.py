"""
Unit test untuk adapters/coretax_djp/api_oauth2_client.py
Menggunakan pytest, mock, dan mocking untuk semua dependency eksternal.
"""

import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

# ============================================================
# MOCK SEMUA MODULE infrastructure SEBELUM IMPORT LAIN
# ============================================================
infra_mock = MagicMock()
caching_mock = MagicMock()
database_mock = MagicMock()
session_factory_mock = MagicMock()
session_factory_mock.get_session_factory = MagicMock()
database_mock.session_factory_sqlalchemy = session_factory_mock
redis_manager_mock = MagicMock()
redis_manager_mock.get_redis_client = AsyncMock(return_value=AsyncMock())
caching_mock.redis_manager = redis_manager_mock
infra_mock.caching = caching_mock
infra_mock.database = database_mock
sys.modules["infrastructure"] = infra_mock
sys.modules["infrastructure.caching"] = caching_mock
sys.modules["infrastructure.caching.redis_manager"] = redis_manager_mock
sys.modules["infrastructure.database"] = database_mock
sys.modules["infrastructure.database.session_factory_sqlalchemy"] = session_factory_mock

# Set environment variables
os.environ.setdefault("CORETAX_CLIENT_ID", "test_client_id")
os.environ.setdefault("CORETAX_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("CORETAX_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn/ygWyF8PbnGy0AHB7MvXl1C0Irrk0VHdN\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("CORETAX_KID", "test_kid")

# ============================================================
# IMPORT MODULE YANG DI-TEST (dengan real dependencies)
# ============================================================
from datetime import UTC, datetime

import pytest

from adapters.coretax_djp.api_oauth2_client import (
    CircuitBreaker,
    CircuitBreakerState,
    ClientMetrics,
    CoretaxAuthError,
    CoretaxCircuitBreakerOpenError,
    CoretaxInvalidResponseError,
    CoretaxNetworkError,
    CoretaxOAuth2Client,
    CoretaxRateLimitError,
    CoretaxTokenExpired,
    Environment,
    GrantType,
    RateLimitStatus,
    TokenResponse,
    close_coretax_client,
    get_coretax_api,
    get_coretax_client,
    reset_coretax_client,
)

# ============================================================
# CLEANUP: lepas fake modules agar tidak meracuni test lain
# yang di-collect setelah file ini (mis. tests/adapters/primary_api/*)
# ============================================================
for _name in [
    "infrastructure",
    "infrastructure.caching",
    "infrastructure.caching.redis_manager",
    "infrastructure.database",
    "infrastructure.database.session_factory_sqlalchemy",
]:
    sys.modules.pop(_name, None)

# ============================================================
# TEST ENVIRONMENT ENUM
# ============================================================
class TestEnvironment:
    """Tests for the Environment enum."""

    def test_members_exist(self):
        """All expected enum members are defined."""
        assert hasattr(Environment, 'SANDBOX')
        assert hasattr(Environment, 'PRODUCTION')
        assert hasattr(Environment, 'MOCK')

    def test_member_is_instance(self):
        """Enum members are instances of the enum class."""
        assert isinstance(Environment.SANDBOX, Environment)
        assert isinstance(Environment.PRODUCTION, Environment)
        assert isinstance(Environment.MOCK, Environment)

    def test_member_values(self):
        """Enum member values are correct."""
        assert Environment.SANDBOX.value == "sandbox"
        assert Environment.PRODUCTION.value == "production"
        assert Environment.MOCK.value == "mock"


# ============================================================
# TEST GRANTTYPE ENUM
# ============================================================
class TestGrantType:
    """Tests for the GrantType enum."""

    def test_members_exist(self):
        """All expected enum members are defined."""
        assert hasattr(GrantType, 'CLIENT_CRED')
        assert hasattr(GrantType, 'JWT_BEARER')
        assert hasattr(GrantType, 'REFRESH')

    def test_member_is_instance(self):
        """Enum members are instances of the enum class."""
        assert isinstance(GrantType.CLIENT_CRED, GrantType)
        assert isinstance(GrantType.JWT_BEARER, GrantType)
        assert isinstance(GrantType.REFRESH, GrantType)

    def test_member_values(self):
        """Enum member values are correct."""
        assert GrantType.CLIENT_CRED.value == "client_credentials"
        assert GrantType.JWT_BEARER.value == "private_key_jwt"
        assert GrantType.REFRESH.value == "refresh_token"


# ============================================================
# TEST TOKENRESPONSE MODEL
# ============================================================
class TestTokenResponse:
    """Tests for the TokenResponse value object / model."""

    def test_construction_success(self):
        """TokenResponse can be constructed with valid field values."""
        instance = TokenResponse(
            access_token="test_access_token",
            token_type="Bearer",
            expires_in=3600,
            refresh_token="test_refresh_token",
            scope="read write",
            issued_at=time.time(),
        )
        assert isinstance(instance, TokenResponse)
        assert instance.access_token == "test_access_token"
        assert instance.token_type == "Bearer"
        assert instance.expires_in == 3600

    def test_expires_at_property(self):
        """expires_at property returns correct value."""
        issued_at = 1000.0
        expires_in = 3600
        instance = TokenResponse(
            access_token="test",
            expires_in=expires_in,
            issued_at=issued_at,
        )
        assert instance.expires_at == issued_at + expires_in

    def test_is_expired_property_not_expired(self):
        """is_expired returns False when token is still valid."""
        instance = TokenResponse(
            access_token="test",
            expires_in=3600,
            issued_at=time.time(),
        )
        assert instance.is_expired is False

    def test_is_expired_property_expired(self):
        """is_expired returns True when token has expired."""
        instance = TokenResponse(
            access_token="test",
            expires_in=1,
            issued_at=time.time() - 100,
        )
        assert instance.is_expired is True

    def test_time_to_expiry_property(self):
        """time_to_expiry returns positive value for valid token."""
        instance = TokenResponse(
            access_token="test",
            expires_in=3600,
            issued_at=time.time(),
        )
        assert instance.time_to_expiry > 0
        assert instance.time_to_expiry <= 3600


# ============================================================
# TEST RATELIMITSTATUS MODEL
# ============================================================
class TestRateLimitStatus:
    """Tests for the RateLimitStatus value object / model."""

    def test_construction_success(self):
        """RateLimitStatus can be constructed with valid field values."""
        instance = RateLimitStatus(
            limit=1000,
            remaining=999,
            reset_at=time.time() + 60,
            retry_after=30,
        )
        assert isinstance(instance, RateLimitStatus)
        assert instance.limit == 1000
        assert instance.remaining == 999

    def test_construction_optional_retry_after(self):
        """RateLimitStatus works without retry_after."""
        instance = RateLimitStatus(
            limit=1000,
            remaining=999,
            reset_at=time.time() + 60,
        )
        assert instance.retry_after is None


# ============================================================
# TEST CLIENTMETRICS MODEL
# ============================================================
class TestClientMetrics:
    """Tests for the ClientMetrics value object / model."""

    def test_construction_success(self):
        """ClientMetrics can be constructed with valid field values."""
        now = datetime.now(UTC)
        instance = ClientMetrics(
            total_requests=10,
            successful_requests=8,
            failed_requests=2,
            total_latency_ms=150.5,
            average_latency_ms=15.05,
            token_refreshes=3,
            token_refresh_failures=1,
            circuit_breaker_trips=0,
            last_request_time=now,
            last_error=None,
        )
        assert isinstance(instance, ClientMetrics)
        assert instance.total_requests == 10
        assert instance.successful_requests == 8

    def test_construction_defaults(self):
        """ClientMetrics works with default values."""
        instance = ClientMetrics()
        assert instance.total_requests == 0
        assert instance.successful_requests == 0
        assert instance.failed_requests == 0


# ============================================================
# TEST EXCEPTIONS
# ============================================================
class TestCoretaxAuthError:
    """Tests for CoretaxAuthError."""

    def test_construction(self):
        """CoretaxAuthError can be instantiated."""
        instance = CoretaxAuthError("Test error message")
        assert isinstance(instance, CoretaxAuthError)
        assert str(instance) == "Test error message"

    def test_construction_no_message(self):
        """CoretaxAuthError can be instantiated without message."""
        instance = CoretaxAuthError()
        assert isinstance(instance, CoretaxAuthError)


class TestCoretaxTokenExpired:
    """Tests for CoretaxTokenExpired."""

    def test_construction(self):
        """CoretaxTokenExpired can be instantiated."""
        instance = CoretaxTokenExpired("Token has expired")
        assert isinstance(instance, CoretaxTokenExpired)
        assert isinstance(instance, CoretaxAuthError)


class TestCoretaxRateLimitError:
    """Tests for CoretaxRateLimitError."""

    def test_construction(self):
        """CoretaxRateLimitError can be instantiated with message and retry_after."""
        instance = CoretaxRateLimitError(message="Rate limited", retry_after=60)
        assert isinstance(instance, CoretaxRateLimitError)
        assert isinstance(instance, CoretaxAuthError)
        assert instance.retry_after == 60

    def test_construction_no_retry_after(self):
        """CoretaxRateLimitError works without retry_after."""
        instance = CoretaxRateLimitError(message="Rate limited")
        assert instance.retry_after is None


class TestCoretaxNetworkError:
    """Tests for CoretaxNetworkError."""

    def test_construction(self):
        """CoretaxNetworkError can be instantiated."""
        instance = CoretaxNetworkError("Network error occurred")
        assert isinstance(instance, CoretaxNetworkError)
        assert isinstance(instance, CoretaxAuthError)


class TestCoretaxCircuitBreakerOpenError:
    """Tests for CoretaxCircuitBreakerOpenError."""

    def test_construction(self):
        """CoretaxCircuitBreakerOpenError can be instantiated."""
        instance = CoretaxCircuitBreakerOpenError("Circuit breaker is open")
        assert isinstance(instance, CoretaxCircuitBreakerOpenError)
        assert isinstance(instance, CoretaxAuthError)


class TestCoretaxInvalidResponseError:
    """Tests for CoretaxInvalidResponseError."""

    def test_construction(self):
        """CoretaxInvalidResponseError can be instantiated."""
        instance = CoretaxInvalidResponseError("Invalid response format")
        assert isinstance(instance, CoretaxInvalidResponseError)
        assert isinstance(instance, CoretaxAuthError)


# ============================================================
# TEST CIRCUITBREAKERSTATE ENUM
# ============================================================
class TestCircuitBreakerState:
    """Tests for the CircuitBreakerState enum."""

    def test_members_exist(self):
        """All expected enum members are defined."""
        assert hasattr(CircuitBreakerState, 'CLOSED')
        assert hasattr(CircuitBreakerState, 'OPEN')
        assert hasattr(CircuitBreakerState, 'HALF_OPEN')

    def test_member_is_instance(self):
        """Enum members are instances of the enum class."""
        assert isinstance(CircuitBreakerState.CLOSED, CircuitBreakerState)
        assert isinstance(CircuitBreakerState.OPEN, CircuitBreakerState)
        assert isinstance(CircuitBreakerState.HALF_OPEN, CircuitBreakerState)

    def test_member_values(self):
        """Enum member values are correct."""
        assert CircuitBreakerState.CLOSED.value == "closed"
        assert CircuitBreakerState.OPEN.value == "open"
        assert CircuitBreakerState.HALF_OPEN.value == "half_open"


# ============================================================
# TEST CIRCUITBREAKER CLASS
# ============================================================
class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    def test_construction(self):
        """CircuitBreaker can be instantiated with parameters."""
        instance = CircuitBreaker(
            name="test_circuit",
            failure_threshold=5,
            recovery_timeout=60.0,
            half_open_max_calls=3,
        )
        assert isinstance(instance, CircuitBreaker)
        assert instance.name == "test_circuit"
        assert instance.failure_threshold == 5
        assert instance.recovery_timeout == 60.0
        assert instance.half_open_max_calls == 3

    def test_initial_state_closed(self):
        """CircuitBreaker starts in CLOSED state."""
        instance = CircuitBreaker(name="test")
        assert instance.state == CircuitBreakerState.CLOSED
        assert instance.is_open is False

    def test_can_execute_when_closed(self):
        """can_execute returns True when state is CLOSED."""
        instance = CircuitBreaker(name="test")
        assert instance.can_execute() is True

    def test_record_success_resets_failure_count(self):
        """record_success resets failure count in CLOSED state."""
        instance = CircuitBreaker(name="test", failure_threshold=5)
        # Simulate some failures
        for _ in range(3):
            instance.record_failure()
        assert instance._failure_count == 3
        # Record success should reset
        instance.record_success()
        assert instance._failure_count == 0

    def test_record_failure_increments_count(self):
        """record_failure increments failure count in CLOSED state."""
        instance = CircuitBreaker(name="test", failure_threshold=5)
        for i in range(1, 4):
            instance.record_failure()
            assert instance._failure_count == i

    def test_opens_after_threshold(self):
        """CircuitBreaker opens after reaching failure threshold."""
        instance = CircuitBreaker(name="test", failure_threshold=3)
        for _ in range(3):
            instance.record_failure()
        assert instance.state == CircuitBreakerState.OPEN
        assert instance.is_open is True
        assert instance.can_execute() is False

    def test_half_open_after_recovery_timeout(self):
        """CircuitBreaker transitions to HALF_OPEN after recovery timeout."""
        instance = CircuitBreaker(
            name="test",
            failure_threshold=1,
            recovery_timeout=0.1,
        )
        instance.record_failure()
        assert instance.state == CircuitBreakerState.OPEN
        # Wait for recovery timeout
        time.sleep(0.15)
        # Access is_open to trigger transition check
        _ = instance.is_open
        assert instance.state == CircuitBreakerState.HALF_OPEN

    def test_record_success_in_half_open_closes(self):
        """record_success in HALF_OPEN state closes the circuit."""
        instance = CircuitBreaker(
            name="test",
            failure_threshold=1,
            recovery_timeout=0.1,
        )
        instance.record_failure()
        time.sleep(0.15)
        _ = instance.is_open  # Trigger transition to HALF_OPEN
        assert instance.state == CircuitBreakerState.HALF_OPEN
        instance.record_success()
        assert instance.state == CircuitBreakerState.CLOSED

    def test_record_failure_in_half_open_opens(self):
        """record_failure in HALF_OPEN state opens the circuit."""
        instance = CircuitBreaker(
            name="test",
            failure_threshold=1,
            recovery_timeout=0.1,
            half_open_max_calls=3,
        )
        instance.record_failure()
        time.sleep(0.15)
        _ = instance.is_open  # Trigger transition to HALF_OPEN
        assert instance.state == CircuitBreakerState.HALF_OPEN
        instance.record_failure()
        assert instance.state == CircuitBreakerState.OPEN

    def test_half_open_max_calls(self):
        """can_execute respects half_open_max_calls limit."""
        instance = CircuitBreaker(
            name="test",
            failure_threshold=1,
            recovery_timeout=0.1,
            half_open_max_calls=2,
        )
        instance.record_failure()
        time.sleep(0.15)
        _ = instance.is_open  # Trigger transition to HALF_OPEN
        # First call allowed
        assert instance.can_execute() is True
        # Second call allowed
        assert instance.can_execute() is True
        # Third call denied
        assert instance.can_execute() is False


# ============================================================
# TEST CORETAXOAUTH2CLIENT CLASS
# ============================================================
class TestCoretaxOAuth2Client:
    """Tests for CoretaxOAuth2Client."""

    @pytest.fixture
    def mock_http_client(self):
        """Create a mock httpx.AsyncClient."""
        client = AsyncMock()
        client.is_closed = False
        client.aclose = AsyncMock()
        return client

    @pytest.fixture
    def mock_redis(self):
        """Create a mock redis client."""
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()
        redis.setex = AsyncMock()
        return redis

    def test_construction(self):
        """CoretaxOAuth2Client can be instantiated."""
        with patch.object(os, 'environ', {
            'CORETAX_CLIENT_ID': 'test_id',
            'CORETAX_CLIENT_SECRET': 'test_secret',
            'CORETAX_PRIVATE_KEY': '-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----',
            'CORETAX_KID': 'test_kid',
        }):
            instance = CoretaxOAuth2Client(env="sandbox", config={})
            assert isinstance(instance, CoretaxOAuth2Client)
            assert instance.env == Environment.SANDBOX

    def test_construction_production_default(self):
        """CoretaxOAuth2Client defaults to production environment."""
        with patch.object(os, 'environ', {
            'CORETAX_CLIENT_ID': 'test_id',
            'CORETAX_CLIENT_SECRET': 'test_secret',
            'CORETAX_PRIVATE_KEY': '-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----',
        }):
            instance = CoretaxOAuth2Client()
            assert instance.env == Environment.PRODUCTION

    @pytest.mark.asyncio
    async def test_close(self, mock_http_client):
        """close method closes http client."""
        with patch.object(os, 'environ', {
            'CORETAX_CLIENT_ID': 'test_id',
            'CORETAX_CLIENT_SECRET': 'test_secret',
            'CORETAX_PRIVATE_KEY': '-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----',
        }):
            instance = CoretaxOAuth2Client(env="mock")
            instance._http_client = mock_http_client
            await instance.close()
            mock_http_client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_when_already_closed(self):
        """close method does nothing if client already closed."""
        with patch.object(os, 'environ', {
            'CORETAX_CLIENT_ID': 'test_id',
            'CORETAX_CLIENT_SECRET': 'test_secret',
            'CORETAX_PRIVATE_KEY': '-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----',
        }):
            instance = CoretaxOAuth2Client(env="mock")
            mock_client = AsyncMock()
            mock_client.is_closed = True
            instance._http_client = mock_client
            await instance.close()
            mock_client.aclose.assert_not_awaited()

    def test_generate_client_assertion(self):
        """_generate_client_assertion creates JWT token."""
        with patch.object(os, 'environ', {
            'CORETAX_CLIENT_ID': 'test_id',
            'CORETAX_CLIENT_SECRET': 'test_secret',
            'CORETAX_PRIVATE_KEY': '-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----',
            'CORETAX_KID': 'test_kid',
        }):
            instance = CoretaxOAuth2Client(env="mock")
            # Mock private_key since we can't create real key
            instance.private_key = MagicMock()
            with patch('adapters.coretax_djp.api_oauth2_client.jwt.encode', return_value="fake_jwt"):
                assertion = instance._generate_client_assertion()
                assert assertion == "fake_jwt"

    def test_generate_client_assertion_no_key_raises(self):
        """_generate_client_assertion raises when no private key."""
        with patch.object(os, 'environ', {
            'CORETAX_CLIENT_ID': 'test_id',
            'CORETAX_CLIENT_SECRET': 'test_secret',
        }):
            instance = CoretaxOAuth2Client(env="mock")
            instance.private_key = None
            with pytest.raises(CoretaxAuthError, match="Private key not configured"):
                instance._generate_client_assertion()

    @pytest.mark.asyncio
    async def test_get_access_token_cached(self, mock_redis):
        """get_access_token returns cached token when available."""
        import json
        cached_token = TokenResponse(
            access_token="cached_token",
            expires_in=3600,
            issued_at=time.time(),
        )
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_token.model_dump()))

        with patch.object(os, 'environ', {
            'CORETAX_CLIENT_ID': 'test_id',
            'CORETAX_CLIENT_SECRET': 'test_secret',
            'CORETAX_PRIVATE_KEY': '-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----',
        }):
            instance = CoretaxOAuth2Client(env="mock")
            instance._redis = mock_redis
            token = await instance.get_access_token()
            assert token == "cached_token"

    @pytest.mark.asyncio
    async def test_get_access_token_force_refresh(self, mock_redis, mock_http_client):
        """get_access_token with force_refresh fetches new token."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={
            "access_token": "new_token",
            "expires_in": 3600,
        })
        mock_http_client.post = AsyncMock(return_value=mock_response)

        with patch.object(os, 'environ', {
            'CORETAX_CLIENT_ID': 'test_id',
            'CORETAX_CLIENT_SECRET': 'test_secret',
            'CORETAX_PRIVATE_KEY': '-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----',
        }):
            instance = CoretaxOAuth2Client(env="mock")
            instance._redis = mock_redis
            instance._http_client = mock_http_client
            instance.private_key = MagicMock()

            with patch('adapters.coretax_djp.api_oauth2_client.jwt.encode', return_value="fake_jwt"):
                token = await instance.get_access_token(force_refresh=True)
                assert token == "new_token"
                mock_http_client.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalidate_token(self):
        """invalidate_token clears current token."""
        with patch.object(os, 'environ', {
            'CORETAX_CLIENT_ID': 'test_id',
            'CORETAX_CLIENT_SECRET': 'test_secret',
            'CORETAX_PRIVATE_KEY': '-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----',
        }):
            instance = CoretaxOAuth2Client(env="mock")
            instance._current_token = TokenResponse(
                access_token="test_token",
                expires_in=3600,
            )
            await instance.invalidate_token()
            assert instance._current_token is None


# ============================================================
# TEST MODULE-LEVEL FUNCTIONS
# ============================================================
@pytest.mark.asyncio
async def test_get_coretax_client():
    """get_coretax_client returns CoretaxOAuth2Client instance."""
    with patch.object(os, 'environ', {
        'CORETAX_CLIENT_ID': 'test_id',
        'CORETAX_CLIENT_SECRET': 'test_secret',
        'CORETAX_PRIVATE_KEY': '-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----',
    }):
        with patch('adapters.coretax_djp.api_oauth2_client.CoretaxOAuth2Client') as mock_class:
            mock_instance = MagicMock()
            mock_class.return_value = mock_instance
            result = await get_coretax_client(env="sandbox", config={})
            assert result is mock_instance
            mock_class.assert_called_once_with(env="sandbox", config={})


@pytest.mark.asyncio
async def test_close_coretax_client():
    """close_coretax_client calls close on client."""
    mock_client = AsyncMock()
    # Patch the global variable directly
    import adapters.coretax_djp.api_oauth2_client as module
    original = module._core_client
    module._core_client = mock_client
    try:
        await close_coretax_client()
        mock_client.close.assert_awaited_once()
        assert module._core_client is None
    finally:
        module._core_client = original


@pytest.mark.asyncio
async def test_reset_coretax_client():
    """reset_coretax_client sets client to None."""
    import adapters.coretax_djp.api_oauth2_client as module
    mock_client = AsyncMock()
    original = module._core_client
    module._core_client = mock_client
    try:
        await reset_coretax_client()
        assert module._core_client is None
    finally:
        module._core_client = original


@pytest.mark.asyncio
async def test_get_coretax_api():
    """get_coretax_api yields client instance."""
    import adapters.coretax_djp.api_oauth2_client as module
    mock_client = MagicMock()
    original = module._core_client
    module._core_client = mock_client
    try:
        gen = get_coretax_api()
        result = await gen.__anext__()
        assert result is mock_client
    finally:
        module._core_client = original


# ============================================================
# TEST EDGE CASES AND ERROR HANDLING
# ============================================================
class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_token_response_default_values(self):
        """TokenResponse uses default values correctly."""
        instance = TokenResponse(access_token="test")
        assert instance.token_type == "Bearer"
        assert instance.expires_in == 3600
        assert instance.refresh_token is None
        assert instance.scope is None

    def test_circuit_breaker_default_parameters(self):
        """CircuitBreaker uses default parameters correctly."""
        instance = CircuitBreaker(name="test")
        assert instance.failure_threshold == 5
        assert instance.recovery_timeout == 60.0
        assert instance.half_open_max_calls == 3

    def test_rate_limit_error_inherits_from_auth_error(self):
        """CoretaxRateLimitError is subclass of CoretaxAuthError."""
        assert issubclass(CoretaxRateLimitError, CoretaxAuthError)

    def test_network_error_inherits_from_auth_error(self):
        """CoretaxNetworkError is subclass of CoretaxAuthError."""
        assert issubclass(CoretaxNetworkError, CoretaxAuthError)

    def test_token_expired_inherits_from_auth_error(self):
        """CoretaxTokenExpired is subclass of CoretaxAuthError."""
        assert issubclass(CoretaxTokenExpired, CoretaxAuthError)