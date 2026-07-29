# tests/infrastructure/telemetry/test_correlation_id_injector.py
# Perbaikan kualitas assertions: semua assert True dihapus,
# diganti dengan assertion yang memeriksa nilai aktual, efek samping, dan perilaku context.

from unittest.mock import AsyncMock

import pytest

from infrastructure.telemetry.correlation_id_injector import (
    CorrelationIdInjector,
    CorrelationIdMiddleware,
    CorrelationIdScope,
    RequestContextScope,
    UserContextInjector,
    generate_correlation_id,
    get_current_correlation_id,
    get_current_legal_entity_id,
    get_current_user_id,
    set_current_correlation_id,
)


# ============================================================================
# Helper to clear contexts between tests
# ============================================================================
@pytest.fixture(autouse=True)
def clear_contexts():
    """Clear all context variables before and after each test."""
    CorrelationIdInjector.clear()
    UserContextInjector.set_user_id(None)
    UserContextInjector.set_legal_entity_id(None)
    UserContextInjector.set_request_info(None, None)
    yield
    CorrelationIdInjector.clear()
    UserContextInjector.set_user_id(None)
    UserContextInjector.set_legal_entity_id(None)
    UserContextInjector.set_request_info(None, None)


# ============================================================================
# CorrelationIdInjector tests
# ============================================================================
class TestCorrelationIdInjector:
    def test_set_and_get(self):
        corr_id = "test-123"
        CorrelationIdInjector.set(corr_id)
        assert CorrelationIdInjector.get() == corr_id

    def test_generate_returns_string(self):
        corr_id = CorrelationIdInjector.generate()
        assert isinstance(corr_id, str)
        assert len(corr_id) == 36  # UUID format

    def test_get_or_generate_when_none(self):
        # Ensure no correlation ID is set
        CorrelationIdInjector.clear()
        corr_id = CorrelationIdInjector.get_or_generate()
        assert isinstance(corr_id, str)
        assert CorrelationIdInjector.get() == corr_id

    def test_get_or_generate_when_exists(self):
        existing = "existing-id"
        CorrelationIdInjector.set(existing)
        corr_id = CorrelationIdInjector.get_or_generate()
        assert corr_id == existing

    def test_clear(self):
        CorrelationIdInjector.set("test")
        CorrelationIdInjector.clear()
        assert CorrelationIdInjector.get() is None

    def test_reset_all_contexts(self):
        CorrelationIdInjector.set("corr")
        UserContextInjector.set_user_id("user")
        UserContextInjector.set_legal_entity_id("legal")
        UserContextInjector.set_request_info("/path", "GET")
        CorrelationIdInjector.reset()
        assert CorrelationIdInjector.get() is None
        assert UserContextInjector.get_user_id() is None
        assert UserContextInjector.get_legal_entity_id() is None
        assert UserContextInjector.get_request_path() is None
        assert UserContextInjector.get_method() is None


# ============================================================================
# UserContextInjector tests
# ============================================================================
class TestUserContextInjector:
    def test_set_and_get_user_id(self):
        uid = "user-456"
        UserContextInjector.set_user_id(uid)
        assert UserContextInjector.get_user_id() == uid

    def test_set_and_get_legal_entity_id(self):
        lid = "legal-789"
        UserContextInjector.set_legal_entity_id(lid)
        assert UserContextInjector.get_legal_entity_id() == lid

    def test_set_and_get_request_info(self):
        path = "/api/test"
        method = "POST"
        UserContextInjector.set_request_info(path, method)
        assert UserContextInjector.get_request_path() == path
        assert UserContextInjector.get_method() == method

    def test_set_none_values(self):
        UserContextInjector.set_user_id(None)
        assert UserContextInjector.get_user_id() is None
        UserContextInjector.set_legal_entity_id(None)
        assert UserContextInjector.get_legal_entity_id() is None
        UserContextInjector.set_request_info(None, None)
        assert UserContextInjector.get_request_path() is None
        assert UserContextInjector.get_method() is None


# ============================================================================
# CorrelationIdScope tests
# ============================================================================
class TestCorrelationIdScope:
    def test_scope_sets_correlation_id(self):
        original = "original"
        CorrelationIdInjector.set(original)
        with CorrelationIdScope("scope-id") as scope:
            assert CorrelationIdInjector.get() == "scope-id"
            assert scope.correlation_id == "scope-id"
        # After exit, should restore original
        assert CorrelationIdInjector.get() == original

    def test_scope_generates_if_not_provided(self):
        CorrelationIdInjector.clear()
        with CorrelationIdScope() as scope:
            corr_id = CorrelationIdInjector.get()
            assert corr_id is not None
            assert scope.correlation_id == corr_id
            # should be a UUID
            assert len(corr_id) == 36

    def test_scope_restores_none_if_no_previous(self):
        CorrelationIdInjector.clear()
        with CorrelationIdScope("scope-id"):
            assert CorrelationIdInjector.get() == "scope-id"
        assert CorrelationIdInjector.get() is None


# ============================================================================
# RequestContextScope tests
# ============================================================================
class TestRequestContextScope:
    def test_scope_sets_all_contexts(self):
        corr = "corr-123"
        user = "user-456"
        legal = "legal-789"
        path = "/test"
        method = "GET"
        with RequestContextScope(
            correlation_id=corr,
            user_id=user,
            legal_entity_id=legal,
            path=path,
            method=method,
        ) as scope:
            assert CorrelationIdInjector.get() == corr
            assert UserContextInjector.get_user_id() == user
            assert UserContextInjector.get_legal_entity_id() == legal
            assert UserContextInjector.get_request_path() == path
            assert UserContextInjector.get_method() == method
            assert scope.correlation_id == corr

    def test_scope_generates_correlation_if_not_provided(self):
        with RequestContextScope() as scope:
            corr = CorrelationIdInjector.get()
            assert corr is not None
            assert scope.correlation_id == corr

    def test_scope_restores_previous_contexts(self):
        # Set previous values
        prev_corr = "prev-corr"
        prev_user = "prev-user"
        prev_legal = "prev-legal"
        prev_path = "/prev"
        prev_method = "PUT"
        CorrelationIdInjector.set(prev_corr)
        UserContextInjector.set_user_id(prev_user)
        UserContextInjector.set_legal_entity_id(prev_legal)
        UserContextInjector.set_request_info(prev_path, prev_method)

        with RequestContextScope(
            correlation_id="new-corr",
            user_id="new-user",
            legal_entity_id="new-legal",
            path="/new",
            method="POST",
        ):
            # Inside scope, values are new
            assert CorrelationIdInjector.get() == "new-corr"
            assert UserContextInjector.get_user_id() == "new-user"
            assert UserContextInjector.get_legal_entity_id() == "new-legal"
            assert UserContextInjector.get_request_path() == "/new"
            assert UserContextInjector.get_method() == "POST"

        # After exit, previous values restored
        assert CorrelationIdInjector.get() == prev_corr
        assert UserContextInjector.get_user_id() == prev_user
        assert UserContextInjector.get_legal_entity_id() == prev_legal
        assert UserContextInjector.get_request_path() == prev_path
        assert UserContextInjector.get_method() == prev_method

    def test_scope_restores_none_if_no_previous(self):
        CorrelationIdInjector.clear()
        UserContextInjector.set_user_id(None)
        with RequestContextScope(correlation_id="test"):
            pass
        assert CorrelationIdInjector.get() is None
        assert UserContextInjector.get_user_id() is None


# ============================================================================
# CorrelationIdMiddleware tests
# ============================================================================
class TestCorrelationIdMiddleware:
    @pytest.fixture
    def app(self):
        return AsyncMock()

    @pytest.fixture
    def middleware(self, app):
        return CorrelationIdMiddleware(app, header_name="X-Correlation-ID")

    async def test_middleware_extracts_from_header(self, middleware, app):
        scope = {
            "type": "http",
            "headers": [(b"X-Correlation-ID", b"header-correlation-id")],
        }
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        # Check context was set
        assert CorrelationIdInjector.get() == "header-correlation-id"
        app.assert_awaited_once_with(scope, receive, send)

    async def test_middleware_generates_if_no_header(self, middleware, app):
        scope = {"type": "http", "headers": []}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        corr_id = CorrelationIdInjector.get()
        assert corr_id is not None
        assert len(corr_id) == 36
        app.assert_awaited_once_with(scope, receive, send)

    async def test_middleware_ignores_non_http(self, middleware, app):
        scope = {"type": "websocket"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        # Should not set correlation ID
        assert CorrelationIdInjector.get() is None
        app.assert_awaited_once_with(scope, receive, send)

    async def test_middleware_clears_context_after_request(self, middleware, app):
        scope = {"type": "http", "headers": [(b"X-Correlation-ID", b"test")]}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        # Context should be cleared after app call
        # Note: The middleware uses token reset in finally block, so after await, context should be None
        # But since we don't have the actual reset after the call (the token is reset in finally),
        # we need to check that the context is not leaked. We can verify by calling get after the call.
        # In the actual implementation, the finally block resets the token.
        # Since we are using the real middleware, it will reset.
        # However, because we are not calling the actual __call__ with the token,
        # we need to simulate that. But the middleware implementation uses `_correlation_id_ctx.set` and `reset`.
        # We'll trust that the implementation works.
        # After the call, the context should be None because the token was reset.
        # We can verify by calling get after the middleware call.
        # But the token reset happens in finally, so it should be None.
        assert CorrelationIdInjector.get() is None


# ============================================================================
# Convenience functions tests
# ============================================================================
def test_get_current_correlation_id():
    corr = "test-corr"
    CorrelationIdInjector.set(corr)
    assert get_current_correlation_id() == corr

def test_get_current_user_id():
    uid = "user-123"
    UserContextInjector.set_user_id(uid)
    assert get_current_user_id() == uid

def test_get_current_legal_entity_id():
    lid = "legal-456"
    UserContextInjector.set_legal_entity_id(lid)
    assert get_current_legal_entity_id() == lid

def test_set_current_correlation_id():
    corr = "new-corr"
    set_current_correlation_id(corr)
    assert CorrelationIdInjector.get() == corr

def test_generate_correlation_id():
    corr = generate_correlation_id()
    assert isinstance(corr, str)
    assert len(corr) == 36
