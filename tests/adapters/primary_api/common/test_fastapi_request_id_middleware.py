# tests/adapters/primary_api/common/test_fastapi_request_id_middleware.py
# Perbaikan kualitas assertions: mengganti semua assert True dengan
# assertion yang memeriksa nilai aktual, efek samping, atau interaksi mock.

import logging
import uuid
from contextvars import ContextVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request
from starlette.responses import Response

from adapters.primary_api.common.fastapi_request_id_middleware import (
    HEADER_CORRELATION_ID,
    HEADER_REQUEST_ID,
    HEADER_TRACE_ID,
    CorrelationIdHandler,
    RequestIDContext,
    RequestIDError,
    RequestIDGenerator,
    RequestIDMiddleware,
    create_request_id_middleware,
    generate_request_id,
    get_current_request_id,
    set_request_id_for_task,
)


# ============================================================================
# RequestIDError tests
# ============================================================================
class TestRequestIDError:
    def test_construction(self):
        error = RequestIDError("test message")
        assert isinstance(error, Exception)
        assert str(error) == "test message"

    def test_default_construction(self):
        error = RequestIDError()
        assert isinstance(error, RequestIDError)
        assert str(error) == ""


# ============================================================================
# RequestIDGenerator tests
# ============================================================================
class TestRequestIDGenerator:
    def test_generate_uuid(self):
        rid = RequestIDGenerator.generate_uuid()
        # check valid UUID format
        try:
            uuid.UUID(rid)
        except ValueError:
            pytest.fail(f"Invalid UUID: {rid}")
        assert len(rid) == 36

    def test_generate_short(self):
        rid = RequestIDGenerator.generate_short()
        assert len(rid) == 8
        # all hex characters
        assert all(c in "0123456789abcdef" for c in rid)

    def test_generate_with_timestamp(self):
        rid = RequestIDGenerator.generate_with_timestamp()
        # format: YYYYMMDDHHMMSS-xxxxxx
        parts = rid.split("-")
        assert len(parts) == 2
        assert len(parts[0]) == 14  # timestamp length
        assert len(parts[1]) == 6   # hex part
        # timestamp should be digits
        assert parts[0].isdigit()
        assert all(c in "0123456789abcdef" for c in parts[1])

    def test_generate_sequential(self):
        rid1 = RequestIDGenerator.generate_sequential("test")
        rid2 = RequestIDGenerator.generate_sequential("test")
        assert rid1.startswith("test-")
        assert rid2.startswith("test-")
        # sequence number should increment
        seq1 = int(rid1.split("-")[1])
        seq2 = int(rid2.split("-")[1])
        assert seq2 == seq1 + 1

    def test_generate_sequential_default_prefix(self):
        rid = RequestIDGenerator.generate_sequential()
        assert rid.startswith("req-")


# ============================================================================
# RequestIDContext tests
# ============================================================================
class TestRequestIDContext:
    def setup_method(self):
        # Clear context before each test
        RequestIDContext.clear()

    def test_set_and_get(self):
        rid = "test-123"
        RequestIDContext.set(rid)
        assert RequestIDContext.get() == rid

    def test_clear(self):
        rid = "test-123"
        RequestIDContext.set(rid)
        RequestIDContext.clear()
        assert RequestIDContext.get() is None

    def test_ensure_request_id_existing(self):
        rid = "existing"
        RequestIDContext.set(rid)
        result = RequestIDContext.ensure_request_id("fallback")
        assert result == rid
        # should not change
        assert RequestIDContext.get() == rid

    def test_ensure_request_id_missing_with_fallback(self):
        RequestIDContext.clear()
        result = RequestIDContext.ensure_request_id("fallback")
        assert result == "fallback"
        assert RequestIDContext.get() == "fallback"

    def test_ensure_request_id_missing_without_fallback(self):
        RequestIDContext.clear()
        result = RequestIDContext.ensure_request_id()
        # should generate a UUID
        try:
            uuid.UUID(result)
        except ValueError:
            pytest.fail(f"Invalid UUID: {result}")
        assert RequestIDContext.get() == result


# ============================================================================
# CorrelationIdHandler tests
# ============================================================================
class TestCorrelationIdHandler:
    def test_emit_with_request_id(self):
        target = MagicMock()
        handler = CorrelationIdHandler(target)
        # create log record
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test", args=(), exc_info=None
        )
        # set request ID in context
        RequestIDContext.set("req-123")
        handler.emit(record)
        assert hasattr(record, "request_id")
        assert record.request_id == "req-123"
        target.emit.assert_called_once_with(record)

    def test_emit_without_request_id(self):
        target = MagicMock()
        handler = CorrelationIdHandler(target)
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test", args=(), exc_info=None
        )
        RequestIDContext.clear()
        handler.emit(record)
        # should not add request_id attribute
        assert not hasattr(record, "request_id")
        target.emit.assert_called_once_with(record)


# ============================================================================
# RequestIDMiddleware tests
# ============================================================================
class TestRequestIDMiddleware:
    @pytest.fixture
    def app(self):
        return AsyncMock()

    @pytest.fixture
    def middleware(self, app):
        return RequestIDMiddleware(
            app,
            header_names=[HEADER_REQUEST_ID, HEADER_CORRELATION_ID],
            generate_if_missing=True,
            add_to_response=True,
            response_header_name=HEADER_REQUEST_ID,
            generator=RequestIDGenerator.generate_uuid,
            inject_to_logging=False,   # avoid logging filters for testing
            inject_to_telemetry=False,
        )

    @pytest.fixture
    def request(self):
        req = MagicMock(spec=Request)
        req.headers = {}
        req.method = "GET"
        req.url = "http://test.com"
        req.state = MagicMock()
        return req

    @pytest.fixture
    def call_next(self):
        async def next_(req):
            return Response("ok")
        return next_

    async def test_dispatch_extract_from_header(self, middleware, request, call_next):
        request.headers = {HEADER_REQUEST_ID: "from-header"}
        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 200
        # check context
        assert RequestIDContext.get() == "from-header"
        assert request.state.request_id == "from-header"
        # response header
        assert response.headers.get(HEADER_REQUEST_ID) == "from-header"
        # after dispatch, context cleared
        assert RequestIDContext.get() is None

    async def test_dispatch_extract_correlation_header(self, middleware, request, call_next):
        request.headers = {HEADER_CORRELATION_ID: "corr-123"}
        response = await middleware.dispatch(request, call_next)
        assert RequestIDContext.get() == "corr-123"
        assert response.headers.get(HEADER_REQUEST_ID) == "corr-123"

    async def test_dispatch_generate_if_missing(self, middleware, request, call_next):
        request.headers = {}
        with patch.object(RequestIDGenerator, "generate_uuid", return_value="generated-123"):
            response = await middleware.dispatch(request, call_next)
        assert RequestIDContext.get() == "generated-123"
        assert response.headers.get(HEADER_REQUEST_ID) == "generated-123"

    async def test_dispatch_no_generate_if_disabled(self, app):
        middleware = RequestIDMiddleware(
            app,
            generate_if_missing=False,
            add_to_response=True,
            inject_to_logging=False,
            inject_to_telemetry=False,
        )
        request = MagicMock(spec=Request)
        request.headers = {}
        request.state = MagicMock()
        call_next = AsyncMock(return_value=Response("ok"))
        response = await middleware.dispatch(request, call_next)
        assert RequestIDContext.get() is None
        assert request.state.request_id is None
        assert HEADER_REQUEST_ID not in response.headers

    async def test_dispatch_response_header_custom(self, app):
        middleware = RequestIDMiddleware(
            app,
            generate_if_missing=True,
            add_to_response=True,
            response_header_name="X-Custom-ID",
            inject_to_logging=False,
            inject_to_telemetry=False,
            generator=RequestIDGenerator.generate_uuid,
        )
        request = MagicMock(spec=Request)
        request.headers = {}
        request.state = MagicMock()
        call_next = AsyncMock(return_value=Response("ok"))
        with patch.object(RequestIDGenerator, "generate_uuid", return_value="custom-456"):
            response = await middleware.dispatch(request, call_next)
        assert response.headers.get("X-Custom-ID") == "custom-456"

    async def test_dispatch_no_response_header(self, app):
        middleware = RequestIDMiddleware(
            app,
            generate_if_missing=True,
            add_to_response=False,
            inject_to_logging=False,
            inject_to_telemetry=False,
            generator=RequestIDGenerator.generate_uuid,
        )
        request = MagicMock(spec=Request)
        request.headers = {}
        request.state = MagicMock()
        call_next = AsyncMock(return_value=Response("ok"))
        with patch.object(RequestIDGenerator, "generate_uuid", return_value="no-header"):
            response = await middleware.dispatch(request, call_next)
        assert HEADER_REQUEST_ID not in response.headers

    async def test_dispatch_preserves_existing_request_id(self, middleware, request, call_next):
        request.headers = {HEADER_REQUEST_ID: "existing"}
        with patch.object(RequestIDGenerator, "generate_uuid", return_value="should-not-use"):
            response = await middleware.dispatch(request, call_next)
        assert RequestIDContext.get() == "existing"
        assert response.headers.get(HEADER_REQUEST_ID) == "existing"

    async def test_dispatch_telemetry_injection(self, app):
        # mock telemetry available
        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=None)

        with patch("adapters.primary_api.common.fastapi_request_id_middleware.TELEMETRY_AVAILABLE", True):
            with patch("adapters.primary_api.common.fastapi_request_id_middleware.get_tracer", return_value=mock_tracer):
                middleware = RequestIDMiddleware(
                    app,
                    generate_if_missing=True,
                    inject_to_logging=False,
                    inject_to_telemetry=True,
                )
                request = MagicMock(spec=Request)
                request.headers = {}
                request.state = MagicMock()
                request.method = "POST"
                request.url = "http://test.com"
                call_next = AsyncMock(return_value=Response("ok"))
                with patch.object(RequestIDGenerator, "generate_uuid", return_value="tele-123"):
                    response = await middleware.dispatch(request, call_next)
        # check span started
        mock_tracer.start_span.assert_called_once_with(
            "http_request",
            attributes={
                "http.request_id": "tele-123",
                "http.method": "POST",
                "http.url": "http://test.com",
            }
        )
        # span attributes set
        mock_span.set_attribute.assert_any_call("http.duration_ms", pytest.approx(0.0, abs=100))
        mock_span.set_attribute.assert_any_call("http.status_code", 200)
        # span exited
        mock_span.__exit__.assert_called_once()

    async def test_dispatch_telemetry_failure(self, app):
        # if get_tracer fails, should disable telemetry silently
        with patch("adapters.primary_api.common.fastapi_request_id_middleware.TELEMETRY_AVAILABLE", True):
            with patch("adapters.primary_api.common.fastapi_request_id_middleware.get_tracer", side_effect=Exception("fail")):
                middleware = RequestIDMiddleware(
                    app,
                    generate_if_missing=True,
                    inject_to_logging=False,
                    inject_to_telemetry=True,
                )
                assert middleware.inject_to_telemetry is False  # disabled after failure

    async def test_dispatch_exception_handling(self, middleware, request):
        # simulate error in call_next
        async def failing_next(req):
            raise ValueError("test error")
        with pytest.raises(ValueError, match="test error"):
            await middleware.dispatch(request, failing_next)
        # context should be cleared even on error
        assert RequestIDContext.get() is None

    # ---- class methods ----
    def test_get_current_request_id(self):
        RequestIDContext.set("test-456")
        result = RequestIDMiddleware.get_current_request_id()
        assert result == "test-456"

    def test_ensure_current_request_id_existing(self):
        RequestIDContext.set("existing")
        result = RequestIDMiddleware.ensure_current_request_id()
        assert result == "existing"

    def test_ensure_current_request_id_missing(self):
        RequestIDContext.clear()
        with patch.object(RequestIDGenerator, "generate_uuid", return_value="new-gen"):
            result = RequestIDMiddleware.ensure_current_request_id()
        assert result == "new-gen"
        assert RequestIDContext.get() == "new-gen"


# ============================================================================
# Utility functions tests
# ============================================================================
def test_get_current_request_id_function():
    RequestIDContext.set("func-test")
    result = get_current_request_id()
    assert result == "func-test"

def test_set_request_id_for_task():
    set_request_id_for_task("task-id")
    assert RequestIDContext.get() == "task-id"

def test_generate_request_id():
    rid = generate_request_id()
    try:
        uuid.UUID(rid)
    except ValueError:
        pytest.fail(f"Invalid UUID: {rid}")


# ============================================================================
# create_request_id_middleware factory test
# ============================================================================
def test_create_request_id_middleware():
    app = MagicMock()
    config = {
        "request_id_headers": ["X-Request-ID", "X-Custom"],
        "generate_if_missing": False,
        "add_to_response": True,
        "response_header_name": "X-Out",
        "inject_to_logging": True,
        "inject_to_telemetry": True,
    }
    middleware = create_request_id_middleware(app, config)
    assert isinstance(middleware, RequestIDMiddleware)
    assert middleware.header_names == ["X-Request-ID", "X-Custom"]
    assert middleware.generate_if_missing is False
    assert middleware.add_to_response is True
    assert middleware.response_header_name == "X-Out"
    assert middleware.inject_to_logging is True
    assert middleware.inject_to_telemetry is True

def test_create_request_id_middleware_defaults():
    app = MagicMock()
    middleware = create_request_id_middleware(app, {})
    assert middleware.header_names == [HEADER_REQUEST_ID, HEADER_CORRELATION_ID]
    assert middleware.generate_if_missing is True
    assert middleware.add_to_response is True
    assert middleware.response_header_name == HEADER_REQUEST_ID
    assert middleware.inject_to_logging is True
    assert middleware.inject_to_telemetry is True