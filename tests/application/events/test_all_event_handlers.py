"""
test_all_event_handlers.py
==========================
Menguji semua event handler yang didefinisikan di application.events.all_event_handlers.
Pendekatan dinamis: impor modul, ambil semua fungsi handle_*, dan parametrize.
"""

import inspect
from unittest.mock import MagicMock, patch

import pytest

from application.events import all_event_handlers as handlers_module
from application.events.publisher_application import EventEnvelope

# Ambil semua fungsi yang namanya diawali "handle_" (kecuali register)
# dan pastikan itu adalah fungsi callable yang memiliki __name__
ALL_HANDLERS = [
    getattr(handlers_module, name)
    for name in dir(handlers_module)
    if name.startswith("handle_")
    and callable(getattr(handlers_module, name))
    and name != "handle_register_all_handlers"
    and hasattr(getattr(handlers_module, name), "__name__")
    and inspect.isfunction(getattr(handlers_module, name))
]

# Filter: hanya yang mengandung "Event" dalam nama fungsinya
EVENT_HANDLERS = [h for h in ALL_HANDLERS if "Event" in h.__name__]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler",
    EVENT_HANDLERS,
    ids=lambda h: h.__name__ if hasattr(h, "__name__") else str(h)
)
async def test_event_handler_logs_info(handler):
    """
    Test bahwa setiap event handler memanggil logger.info setidaknya sekali.
    Assertion: after > before (bermakna).
    """
    with patch("application.events.all_event_handlers.logger") as mock_logger:
        envelope = MagicMock(spec=EventEnvelope)
        envelope.event = "dummy_event"

        before = mock_logger.info.call_count
        await handler(envelope)
        after = mock_logger.info.call_count

        assert after > before, f"Expected logger.info to be called for {handler.__name__}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler",
    EVENT_HANDLERS,
    ids=lambda h: h.__name__ if hasattr(h, "__name__") else str(h)
)
async def test_event_handler_handles_invalid_envelope(handler):
    """
    Negative path: pastikan handler tidak raise exception
    meskipun envelope.event = None.
    """
    with patch("application.events.all_event_handlers.logger"):
        envelope = MagicMock(spec=EventEnvelope)
        envelope.event = None  # invalid

        try:
            await handler(envelope)
        except Exception as e:
            pytest.fail(f"Handler {handler.__name__} raised {e} on None envelope")


def test_register_all_handlers_returns_int():
    """
    Verifikasi register_all_handlers mengembalikan integer.
    """
    registry_mock = MagicMock()
    try:
        count = handlers_module.register_all_handlers(registry=registry_mock)
    except Exception as e:
        pytest.fail(f"register_all_handlers raised {e}")

    assert isinstance(count, int), "register_all_handlers should return an integer"
