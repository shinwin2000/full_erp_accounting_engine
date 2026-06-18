#!/usr/bin/env python3
"""
Module: test_command_dispatcher.py
Layer: Tests / Unit / Kernel

Responsibility:
    Unit tests untuk command dispatcher dan handler registry.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from kernel.command_dispatcher import CommandDispatcher
from kernel.command_envelope import CommandEnvelope, CommandResult
from kernel.command_handler_registry import CommandHandlerRegistry


@dataclass(kw_only=True)
class DummyCommand:
    id: str
    amount: int


class DummyHandler:
    def handle(self, command: DummyCommand) -> CommandResult:
        return CommandResult.success(data=f"Processed {command.id}")


class FailingHandler:
    def handle(self, command: DummyCommand) -> CommandResult:
        raise ValueError("Handler error")


def test_command_dispatcher_dispatch_success():
    registry = CommandHandlerRegistry()
    handler = DummyHandler()
    registry.register(DummyCommand, handler)
    dispatcher = CommandDispatcher(registry)
    envelope = CommandEnvelope(command=DummyCommand(id="001", amount=100))
    result = dispatcher.dispatch(envelope)
    assert result.is_success
    assert result.data == "Processed 001"


def test_command_dispatcher_dispatch_failure():
    registry = CommandHandlerRegistry()
    handler = FailingHandler()
    registry.register(DummyCommand, handler)
    dispatcher = CommandDispatcher(registry)
    envelope = CommandEnvelope(command=DummyCommand(id="002", amount=200))
    result = dispatcher.dispatch(envelope)
    assert result.is_failure
    assert "Handler error" in result.error


def test_command_dispatcher_with_middleware():
    registry = CommandHandlerRegistry()
    handler = DummyHandler()
    registry.register(DummyCommand, handler)
    dispatcher = CommandDispatcher(registry)

    # Add logging middleware
    def log_middleware(envelope, next_handler):
        print(f"Before: {envelope.command.id}")
        result = next_handler(envelope)
        print(f"After: {result.is_success}")
        return result

    dispatcher.add_middleware(log_middleware)
    envelope = CommandEnvelope(command=DummyCommand(id="003", amount=300))
    result = dispatcher.dispatch(envelope)
    assert result.is_success


def test_command_dispatcher_unregistered_command():
    registry = CommandHandlerRegistry()
    dispatcher = CommandDispatcher(registry)
    envelope = CommandEnvelope(command=DummyCommand(id="004", amount=400))
    with pytest.raises(KeyError, match="No handler registered"):
        dispatcher.dispatch(envelope)


def test_command_dispatcher_with_validation():
    registry = CommandHandlerRegistry()
    handler = DummyHandler()
    registry.register(DummyCommand, handler)
    dispatcher = CommandDispatcher(registry)

    def validate(command: DummyCommand) -> bool:
        return command.amount > 0

    dispatcher.set_validator(validate)
    envelope = CommandEnvelope(command=DummyCommand(id="005", amount=-100))
    result = dispatcher.dispatch(envelope)
    assert result.is_failure
    assert "Validation failed" in result.error


if __name__ == "__main__":
    pytest.main([__file__])
