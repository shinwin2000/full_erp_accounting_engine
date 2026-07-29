"""
core/workers.py
================
Infrastruktur threading generik agar setiap pemanggilan API (blocking,
via `requests`) tidak pernah membekukan UI thread PySide6.

Pemakaian:
    run_task(
        self,
        fn=lambda: api_client.get("/coa/accounts"),
        on_success=self._populate_table,
        on_error=self._show_error,
    )
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class _WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(str)


class _Worker(QRunnable):
    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = _WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:
            self.signals.error.emit(_format_exception(exc))
        else:
            self.signals.finished.emit(result)


def _format_exception(exc: Exception) -> str:
    # Import lokal untuk menghindari circular import
    from core.api_client import ApiError, AuthRequiredError, ConnectionFailedError

    if isinstance(exc, ApiError):
        return exc.human_message()
    if isinstance(exc, ConnectionFailedError):
        return str(exc)
    if isinstance(exc, AuthRequiredError):
        return "AUTH_REQUIRED"
    return str(exc)


_pool = QThreadPool.globalInstance()
_pool.setMaxThreadCount(max(8, _pool.maxThreadCount()))


def run_task(
    fn: Callable[..., Any],
    on_success: Callable[[Any], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    *args: Any,
    **kwargs: Any,
) -> _Worker:
    """Menjalankan `fn(*args, **kwargs)` di background thread."""
    worker = _Worker(fn, *args, **kwargs)
    if on_success:
        worker.signals.finished.connect(on_success)
    if on_error:
        worker.signals.error.connect(on_error)
    _pool.start(worker)
    return worker
