#!/usr/bin/env python3
"""
Module: test_command_dispatcher.py
Layer: Tests / Unit / Kernel

Responsibility:
    Unit tests untuk command dispatcher dan handler registry.
    Menggunakan implementasi nyata (real code).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

import pytest

from kernel.command_dispatcher import (
    CommandDispatcher,
    DispatchPriority,
    DispatchStrategy,
    get_command_dispatcher,
)
from kernel.command_envelope import CommandEnvelope, CommandResult, CommandStatus
from kernel.command_handler_registry import HandlerNotFoundError, get_handler_registry


# ============================================================================
# Domain Command & Handlers
# ============================================================================
@dataclass(kw_only=True)
class DummyCommand:
    id: str
    amount: int


def dummy_handler(command: DummyCommand) -> CommandResult:
    return CommandResult.success(data=f"Processed {command.id}")


def failing_handler(command: DummyCommand) -> CommandResult:
    raise ValueError("Handler error")


# ============================================================================
# Helper: buat CommandEnvelope
# ============================================================================
def create_envelope(command: DummyCommand) -> CommandEnvelope:
    return CommandEnvelope(
        command_id=str(uuid4()),
        command_type=command.__class__.__name__,
        command_data=command,
        idempotency_key=str(uuid4()),
        user_id=str(uuid4()),
        legal_entity_id=str(uuid4()),
        timestamp=datetime.utcnow(),
        correlation_id=str(uuid4()),
        causation_id=str(uuid4()),
    )


# ============================================================================
# Fixtures: registry dan dispatcher (singleton)
# ============================================================================
@pytest.fixture(autouse=True)
def reset_registry():
    """Bersihkan registry sebelum setiap test."""
    registry = get_handler_registry()
    registry.clear()  # asumsikan ada method clear()
    yield
    registry.clear()


@pytest.fixture
def dispatcher() -> CommandDispatcher:
    """Kembalikan instance singleton CommandDispatcher."""
    return get_command_dispatcher()


# ============================================================================
# Test Cases
# ============================================================================
@pytest.mark.asyncio
async def test_command_dispatcher_dispatch_success(dispatcher: CommandDispatcher):
    registry = get_handler_registry()
    registry.register(DummyCommand, dummy_handler)

    envelope = create_envelope(DummyCommand(id="001", amount=100))
    # Gunakan strategi DIRECT agar handler langsung dieksekusi
    result_envelope = await dispatcher.dispatch(
        envelope,
        strategy=DispatchStrategy.DIRECT
    )

    assert result_envelope.status == CommandStatus.SUCCESS
    assert result_envelope.result is not None
    assert result_envelope.result.data == "Processed 001"


@pytest.mark.asyncio
async def test_command_dispatcher_dispatch_failure(dispatcher: CommandDispatcher):
    registry = get_handler_registry()
    registry.register(DummyCommand, failing_handler)

    envelope = create_envelope(DummyCommand(id="002", amount=200))
    result_envelope = await dispatcher.dispatch(
        envelope,
        strategy=DispatchStrategy.DIRECT
    )

    # Handler error -> status FAILED, error diisi
    assert result_envelope.status == CommandStatus.FAILED
    assert result_envelope.error is not None
    assert "Handler error" in result_envelope.error


@pytest.mark.asyncio
async def test_command_dispatcher_unregistered_command(dispatcher: CommandDispatcher):
    # Tidak ada handler didaftarkan
    envelope = create_envelope(DummyCommand(id="004", amount=400))

    # dispatch akan melempar HandlerNotFoundError setelah mengisi status REJECTED di envelope
    with pytest.raises(HandlerNotFoundError):
        result_envelope = await dispatcher.dispatch(
            envelope,
            strategy=DispatchStrategy.DIRECT
        )
        # Seharusnya tidak sampai sini, tapi kita bisa periksa status
        # assert result_envelope.status == CommandStatus.REJECTED
        # assert "No handler" in result_envelope.error


# ============================================================================
# Test untuk strategi QUEUE (tanpa worker) – status tetap PENDING
# ============================================================================
@pytest.mark.asyncio
async def test_command_dispatcher_queue_mode(dispatcher: CommandDispatcher):
    registry = get_handler_registry()
    registry.register(DummyCommand, dummy_handler)

    envelope = create_envelope(DummyCommand(id="005", amount=500))
    # Default strategy adalah PRIORITY_QUEUE, atau kita tentukan secara eksplisit
    result_envelope = await dispatcher.dispatch(
        envelope,
        strategy=DispatchStrategy.PRIORITY_QUEUE
    )

    # Karena tidak ada worker yang berjalan, status tetap PENDING
    assert result_envelope.status == CommandStatus.PENDING
    assert result_envelope.result is None


# ============================================================================
# Catatan: Middleware dan Validator tidak ada di implementasi saat ini
# ============================================================================
# def test_middleware_not_implemented():
#     pytest.skip("Middleware not implemented in CommandDispatcher")
#
# def test_validator_not_implemented():
#     pytest.skip("Validator not implemented in CommandDispatcher")


if __name__ == "__main__":
    pytest.main([__file__])