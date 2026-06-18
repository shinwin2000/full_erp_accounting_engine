#!/usr/bin/env python3
"""
Module: test_audit_hook_injector.py
Layer: Tests / Unit / Kernel

Responsibility:
    Unit tests untuk audit hook injector (AOP untuk audit logging).
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from kernel.audit_hook_injector import AuditHookInjector, audit


class DummyService:
    @audit(action="CREATE_USER")
    def create_user(self, user_id: str, name: str) -> str:
        return f"User {user_id} created"

    def internal_method(self):
        pass


def test_audit_decorator_calls_audit_logger():
    mock_logger = Mock()
    injector = AuditHookInjector(logger=mock_logger)
    service = DummyService()
    injector.inject(service)

    service.create_user("123", "Alice")
    mock_logger.log.assert_called_once()
    args = mock_logger.log.call_args[0][0]
    assert args["action"] == "CREATE_USER"
    assert args["user_id"] == "123"
    assert args["name"] == "Alice"
    assert "timestamp" in args


def test_audit_decorator_handles_exception():
    mock_logger = Mock()
    injector = AuditHookInjector(logger=mock_logger)
    service = DummyService()
    injector.inject(service)

    @audit(action="FAILING")
    def failing():
        raise ValueError("Boom")

    with pytest.raises(ValueError):
        failing()
    mock_logger.log.assert_called()
    call_args = mock_logger.log.call_args[0][0]
    assert call_args["error"] == "Boom"


def test_audit_injector_only_injects_decorated_methods():
    mock_logger = Mock()
    injector = AuditHookInjector(logger=mock_logger)
    service = DummyService()
    injector.inject(service)

    # internal_method tidak didekorasi, tidak boleh memanggil logger
    service.internal_method()
    mock_logger.log.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__])
