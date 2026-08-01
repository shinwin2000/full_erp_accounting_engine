# tests/adapters/primary_api/common/test_fastapi_rate_limit_middleware.py
"""
Comprehensive tests for FastAPI Rate Limit Middleware.
Covers all private helper methods, rate limiter backends (memory fallback),
and middleware dispatch behavior.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request
from starlette.responses import Response

from adapters.primary_api.common.fastapi_rate_limit_middleware import (
    FixedWindowRateLimiter,
    RateLimitMiddleware,
    RateLimitStrategy,
    SlidingWindowRateLimiter,
    TokenBucketRateLimiter,
    create_rate_limit_middleware,
    get_redis_rate_limiter,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_app():
    """Mock ASGI app that returns a simple response."""
    async def app(scope, receive, send):
        response = Response("OK", status_code=200)
        await response(scope, receive, send)
    return app


@pytest.fixture
def mock_request():
    """Create a mock request with state and client info."""
    request = MagicMock(spec=Request)
    request.url.path = "/api/test"
    request.headers = {}
    request.client = MagicMock()
    request.client.host = "192.168.1.1"
    request.state = MagicMock()
    request.state.user_id = "user-123"
    request.state.user = MagicMock()
    request.state.user.roles = ["user"]
    return request


@pytest.fixture
def middleware(mock_app):
    """Create a RateLimitMiddleware instance with default config."""
    return RateLimitMiddleware(
        app=mock_app,
        calls_per_minute=60,
        calls_per_second=10,
        strategy=RateLimitStrategy.SLIDING_WINDOW,
        key_by="user",
        exclude_paths=["/api/health"],
        exclude_roles=["admin"],
        redis_client=None,  # force memory fallback
        fallback_to_memory=True,
    )


# ============================================================================
# Tests for SlidingWindowRateLimiter._check_memory
# ============================================================================

class TestSlidingWindowRateLimiter:
    @pytest.fixture
    def limiter(self):
        return SlidingWindowRateLimiter(redis_client=None, fallback_to_memory=True)

    def test_check_memory_allowed(self, limiter):
        """Test memory sliding window allows requests within limit."""
        key = "test-key"
        limit = 5
        window_seconds = 60

        # Simulate multiple requests
        for i in range(limit):
            allowed, remaining, reset_time = limiter._check_memory(key, limit, window_seconds)
            assert allowed is True
            assert remaining == limit - (i + 1)
            assert reset_time > time.time()

        # Next request should exceed limit
        allowed, remaining, reset_time = limiter._check_memory(key, limit, window_seconds)
        assert allowed is False
        assert remaining == 0
        assert reset_time > time.time()

    def test_check_memory_window_expiry(self, limiter):
        """Test that old timestamps are cleared from the window."""
        key = "test-key"
        limit = 3
        window_seconds = 1  # 1 second window

        # Add requests with time manipulation
        limiter._memory_store[key] = [time.time() - 2]  # older than window
        allowed, remaining, reset_time = limiter._check_memory(key, limit, window_seconds)
        # The old entry should be removed, and we should have space
        assert allowed is True
        assert len(limiter._memory_store[key]) == 1  # only the new request

    def test_check_memory_fallback_disabled(self):
        """When fallback is disabled and no redis, should allow all."""
        limiter = SlidingWindowRateLimiter(redis_client=None, fallback_to_memory=False)
        allowed, remaining, reset_time = limiter._check_memory("key", 1, 60)
        # Actually _check_memory is only called if fallback_to_memory is True.
        # If False, the is_allowed method will go to the else branch and allow without calling _check_memory.
        # So we test is_allowed directly.
        allowed, remaining, reset_time = asyncio.run(
            limiter.is_allowed("key", 1, 60)
        )
        assert allowed is True
        assert remaining == 0  # limit - 1


# ============================================================================
# Tests for FixedWindowRateLimiter._check_memory
# ============================================================================

class TestFixedWindowRateLimiter:
    @pytest.fixture
    def limiter(self):
        return FixedWindowRateLimiter(redis_client=None, fallback_to_memory=True)

    def test_check_memory_allowed(self, limiter):
        key = "test-key"
        limit = 3
        window_seconds = 60
        now = time.time()
        # Simulate requests
        for i in range(limit):
            allowed, remaining, reset_time = limiter._check_memory(key, limit, window_seconds)
            assert allowed is True
            assert remaining == limit - (i + 1)
            # Reset time should be at next window boundary
            assert reset_time > now

        # Exceed limit
        allowed, remaining, reset_time = limiter._check_memory(key, limit, window_seconds)
        assert allowed is False
        assert remaining == 0

    def test_check_memory_window_reset(self, limiter):
        """When window changes, counter resets."""
        key = "test-key"
        limit = 2
        window_seconds = 60
        # Force a window number
        now = time.time()
        window_start = int(now // window_seconds) * window_seconds
        limiter._memory_store[key] = (limit, window_start)  # full
        # Now simulate a new window by advancing time beyond window
        with patch('time.time', return_value=now + window_seconds + 1):
            allowed, remaining, reset_time = limiter._check_memory(key, limit, window_seconds)
            assert allowed is True
            assert remaining == limit - 1
            # counter should be reset to 1
            assert limiter._memory_store[key][0] == 1

    def test_check_memory_fallback_disabled(self):
        limiter = FixedWindowRateLimiter(redis_client=None, fallback_to_memory=False)
        allowed, remaining, reset_time = asyncio.run(
            limiter.is_allowed("key", 1, 60)
        )
        assert allowed is True


# ============================================================================
# Tests for TokenBucketRateLimiter._check_memory
# ============================================================================

class TestTokenBucketRateLimiter:
    @pytest.fixture
    def limiter(self):
        return TokenBucketRateLimiter(redis_client=None, fallback_to_memory=True)

    def test_check_memory_allowed(self, limiter):
        key = "test-key"
        capacity = 5
        refill_rate = 1
        interval = 1
        time.time()
        # First request consumes a token
        allowed, remaining, reset_time = limiter._check_memory(key, capacity, refill_rate, interval)
        assert allowed is True
        assert remaining == capacity - 1
        # Subsequent requests consume tokens
        for i in range(capacity - 1):
            allowed, remaining, reset_time = limiter._check_memory(key, capacity, refill_rate, interval)
            assert allowed is True
            assert remaining == capacity - (i + 2)
        # Exceed capacity
        allowed, remaining, reset_time = limiter._check_memory(key, capacity, refill_rate, interval)
        assert allowed is False
        assert remaining == 0

    def test_check_memory_refill(self, limiter):
        key = "test-key"
        capacity = 3
        refill_rate = 1
        interval = 1
        # Consume all tokens
        for _ in range(capacity):
            limiter._check_memory(key, capacity, refill_rate, interval)
        # Now advance time to refill
        now = time.time()
        with patch('time.time', return_value=now + interval + 0.1):
            allowed, remaining, reset_time = limiter._check_memory(key, capacity, refill_rate, interval)
            assert allowed is True
            # tokens should be refilled by 1 (since elapsed=1 interval)
            assert remaining == 1  # capacity - 2 (one consumed, one left)

    def test_check_memory_fallback_disabled(self):
        limiter = TokenBucketRateLimiter(redis_client=None, fallback_to_memory=False)
        allowed, remaining, reset_time = asyncio.run(
            limiter.is_allowed("key", 1, 1, 1)
        )
        assert allowed is True


# ============================================================================
# Tests for RateLimitMiddleware private methods
# ============================================================================

class TestRateLimitMiddlewarePrivate:
    def test_init_limiter_sliding_window(self, middleware):
        middleware._init_limiter(None, True)
        assert isinstance(middleware._limiter, SlidingWindowRateLimiter)

    def test_init_limiter_fixed_window(self, middleware):
        middleware.strategy = RateLimitStrategy.FIXED_WINDOW
        middleware._init_limiter(None, True)
        assert isinstance(middleware._limiter, FixedWindowRateLimiter)

    def test_init_limiter_token_bucket(self, middleware):
        middleware.strategy = RateLimitStrategy.TOKEN_BUCKET
        middleware._init_limiter(None, True)
        assert isinstance(middleware._limiter, TokenBucketRateLimiter)

    def test_init_limiter_default(self, middleware):
        middleware.strategy = "unknown"
        middleware._init_limiter(None, True)
        assert isinstance(middleware._limiter, SlidingWindowRateLimiter)

    def test_get_client_ip_from_forwarded(self, middleware, mock_request):
        mock_request.headers = {"X-Forwarded-For": "10.0.0.1, 192.168.1.1"}
        ip = middleware._get_client_ip(mock_request)
        assert ip == "10.0.0.1"

    def test_get_client_ip_from_real_ip(self, middleware, mock_request):
        mock_request.headers = {"X-Real-IP": "10.0.0.2"}
        ip = middleware._get_client_ip(mock_request)
        assert ip == "10.0.0.2"

    def test_get_client_ip_fallback(self, middleware, mock_request):
        mock_request.headers = {}
        mock_request.client.host = "192.168.1.100"
        ip = middleware._get_client_ip(mock_request)
        assert ip == "192.168.1.100"

    def test_get_client_ip_no_client(self, middleware):
        request = MagicMock(spec=Request)
        request.headers = {}
        request.client = None
        ip = middleware._get_client_ip(request)
        assert ip == "unknown"

    def test_get_user_id_from_state_user_id(self, middleware, mock_request):
        mock_request.state.user_id = "user-456"
        uid = middleware._get_user_id(mock_request)
        assert uid == "user-456"

    def test_get_user_id_from_state_user(self, middleware, mock_request):
        mock_request.state.user_id = None
        mock_request.state.user.user_id = "user-789"
        uid = middleware._get_user_id(mock_request)
        assert uid == "user-789"

    def test_get_user_id_no_user(self, middleware, mock_request):
        mock_request.state.user_id = None
        mock_request.state.user = None
        uid = middleware._get_user_id(mock_request)
        assert uid is None

    def test_get_user_role_from_state(self, middleware, mock_request):
        mock_request.state.user.roles = ["editor", "viewer"]
        role = middleware._get_user_role(mock_request)
        assert role == "editor"

    def test_get_user_role_no_roles(self, middleware, mock_request):
        mock_request.state.user.roles = []
        role = middleware._get_user_role(mock_request)
        assert role is None

    def test_get_user_role_no_user(self, middleware, mock_request):
        mock_request.state.user = None
        role = middleware._get_user_role(mock_request)
        assert role is None

    def test_get_rate_limit_key_excluded_path(self, middleware, mock_request):
        mock_request.url.path = "/api/health"
        key = middleware._get_rate_limit_key(mock_request)
        assert key is None

    def test_get_rate_limit_key_excluded_role(self, middleware, mock_request):
        mock_request.state.user.roles = ["admin"]
        key = middleware._get_rate_limit_key(mock_request)
        assert key is None

    def test_get_rate_limit_key_user(self, middleware, mock_request):
        mock_request.state.user_id = "user123"
        key = middleware._get_rate_limit_key(mock_request)
        assert key is not None
        # Key should be hashed sha256 of "user:user123" prefix
        import hashlib
        expected_raw = "user:user123"
        expected_hash = hashlib.sha256(expected_raw.encode()).hexdigest()[:32]
        assert key == expected_hash

    def test_get_rate_limit_key_ip(self, middleware, mock_request):
        middleware.key_by = "ip"
        mock_request.client.host = "10.0.0.5"
        key = middleware._get_rate_limit_key(mock_request)
        expected_raw = "ip:10.0.0.5"
        import hashlib
        expected_hash = hashlib.sha256(expected_raw.encode()).hexdigest()[:32]
        assert key == expected_hash

    def test_get_rate_limit_key_user_ip(self, middleware, mock_request):
        middleware.key_by = "user_ip"
        mock_request.state.user_id = "user123"
        mock_request.client.host = "10.0.0.5"
        key = middleware._get_rate_limit_key(mock_request)
        expected_raw = "user:user123:ip:10.0.0.5"
        import hashlib
        expected_hash = hashlib.sha256(expected_raw.encode()).hexdigest()[:32]
        assert key == expected_hash

    def test_get_rate_limit_key_fallback(self, middleware, mock_request):
        middleware.key_by = "unknown"
        mock_request.client.host = "10.0.0.5"
        key = middleware._get_rate_limit_key(mock_request)
        expected_raw = "ip:10.0.0.5"
        import hashlib
        expected_hash = hashlib.sha256(expected_raw.encode()).hexdigest()[:32]
        assert key == expected_hash


# ============================================================================
# Tests for RateLimitMiddleware.dispatch (integration)
# ============================================================================

class TestRateLimitMiddlewareDispatch:
    @pytest.fixture
    def app(self):
        async def app(scope, receive, send):
            response = Response("OK", status_code=200)
            await response(scope, receive, send)
        return app

    @pytest.fixture
    def middleware(self, app):
        return RateLimitMiddleware(
            app=app,
            calls_per_minute=2,
            strategy=RateLimitStrategy.SLIDING_WINDOW,
            key_by="user",
            redis_client=None,
            fallback_to_memory=True,
        )

    @pytest.mark.asyncio
    async def test_dispatch_allowed(self, middleware):
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "1.2.3.4"
        request.state = MagicMock()
        request.state.user_id = "user123"
        request.state.user = None

        # Mock the limiter to return allowed
        middleware._limiter.is_allowed = AsyncMock(return_value=(True, 5, time.time() + 60))
        call_next = AsyncMock(return_value=Response("OK", status_code=200))

        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 200
        # Headers should be added
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers

    @pytest.mark.asyncio
    async def test_dispatch_rate_limited(self, middleware):
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "1.2.3.4"
        request.state = MagicMock()
        request.state.user_id = "user123"
        request.state.user = None

        reset_time = time.time() + 30
        middleware._limiter.is_allowed = AsyncMock(return_value=(False, 0, reset_time))
        call_next = AsyncMock()

        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 429
        call_next.assert_not_called()
        # Check headers
        assert response.headers["X-RateLimit-Limit"] == str(middleware.calls_per_minute)
        assert response.headers["X-RateLimit-Remaining"] == "0"
        assert response.headers["X-RateLimit-Reset"] == str(int(reset_time))
        assert response.headers["Retry-After"] == str(int(reset_time - time.time()))
        # Check JSON content
        content = response.body
        import json
        data = json.loads(content)
        assert data["detail"] == "Rate limit exceeded. Please retry later."

    @pytest.mark.asyncio
    async def test_dispatch_excluded_path(self, middleware):
        request = MagicMock(spec=Request)
        request.url.path = "/api/health"
        request.state = MagicMock()
        call_next = AsyncMock(return_value=Response("OK", status_code=200))

        # Limiter should not be called
        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 200
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_excluded_role(self, middleware):
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.state = MagicMock()
        request.state.user_id = "admin"
        request.state.user = MagicMock()
        request.state.user.roles = ["admin"]
        call_next = AsyncMock(return_value=Response("OK", status_code=200))

        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 200
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_limiter_error_fallback(self, middleware):
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "1.2.3.4"
        request.state = MagicMock()
        request.state.user_id = "user123"
        request.state.user = None

        # Simulate limiter throwing exception
        middleware._limiter.is_allowed = AsyncMock(side_effect=Exception("Redis down"))
        call_next = AsyncMock(return_value=Response("OK", status_code=200))

        response = await middleware.dispatch(request, call_next)
        # Should allow request and not raise
        assert response.status_code == 200
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_token_bucket_strategy(self, app):
        middleware = RateLimitMiddleware(
            app=app,
            calls_per_minute=60,
            calls_per_second=10,
            strategy=RateLimitStrategy.TOKEN_BUCKET,
            key_by="user",
            redis_client=None,
            fallback_to_memory=True,
        )
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "1.2.3.4"
        request.state = MagicMock()
        request.state.user_id = "user123"
        request.state.user = None

        # Mock limiter
        middleware._limiter.is_allowed = AsyncMock(return_value=(True, 10, time.time() + 60))
        call_next = AsyncMock(return_value=Response("OK", status_code=200))

        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 200
        # Token bucket uses capacity (calls_per_minute) and refill_rate (calls_per_second)
        # We check that is_allowed was called with correct args
        middleware._limiter.is_allowed.assert_called_with(
            middleware._get_rate_limit_key(request),
            middleware.calls_per_minute,
            middleware.calls_per_second,
            1
        )


# ============================================================================
# Tests for helper functions
# ============================================================================

async def test_get_redis_rate_limiter_success():
    with patch('adapters.primary_api.common.fastapi_rate_limit_middleware.REDIS_AVAILABLE', True), \
         patch('adapters.primary_api.common.fastapi_rate_limit_middleware.get_redis_client') as mock_get:
        mock_get.return_value = AsyncMock()
        client = await get_redis_rate_limiter()
        assert client is not None


async def test_get_redis_rate_limiter_not_available():
    with patch('adapters.primary_api.common.fastapi_rate_limit_middleware.REDIS_AVAILABLE', False):
        client = await get_redis_rate_limiter()
        assert client is None


async def test_get_redis_rate_limiter_exception():
    with patch('adapters.primary_api.common.fastapi_rate_limit_middleware.REDIS_AVAILABLE', True), \
         patch('adapters.primary_api.common.fastapi_rate_limit_middleware.get_redis_client', side_effect=Exception("Connection failed")):
        client = await get_redis_rate_limiter()
        assert client is None


def test_create_rate_limit_middleware():
    app = MagicMock()
    config = {
        "rate_limit_calls_per_minute": 120,
        "rate_limit_calls_per_second": 20,
        "rate_limit_strategy": RateLimitStrategy.FIXED_WINDOW,
        "rate_limit_key_by": "ip",
        "rate_limit_exclude_paths": ["/exclude"],
        "rate_limit_exclude_roles": ["superadmin"],
        "rate_limit_fallback_memory": False,
    }
    middleware = create_rate_limit_middleware(app, config)
    assert isinstance(middleware, RateLimitMiddleware)
    assert middleware.calls_per_minute == 120
    assert middleware.calls_per_second == 20
    assert middleware.strategy == RateLimitStrategy.FIXED_WINDOW
    assert middleware.key_by == "ip"
    assert "/exclude" in middleware.exclude_paths
    assert "superadmin" in middleware.exclude_roles
    # redis_client is None by default; fallback_to_memory is False
    assert middleware._limiter.fallback_to_memory is False
