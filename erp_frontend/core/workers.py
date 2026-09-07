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

# ---------------------------------------------------------------------------
# PENTING - fix untuk bug "RuntimeError: Signal source has been deleted":
#
# `run_task()` sebelumnya membuat `_Worker` lalu langsung menyerahkannya ke
# `_pool.start(worker)` tanpa menyimpan referensi Python-nya di manapun
# (pemanggil di seluruh app, mis. generic_list_page.py, mengabaikan nilai
# balik run_task()). QRunnable BUKAN QObject, jadi ia tidak dijaga hidup
# lewat mekanisme parent-child Qt biasa - satu-satunya yang menjaga objek
# `_Worker` (dan `self.signals` miliknya) tetap hidup adalah referensi
# Python. Begitu tidak ada referensi Python yang tersisa, garbage collector
# CPython bisa menghapus objek tsb SEMENTARA `run()` masih berjalan di
# background thread. Kalau itu terjadi pas request baru saja
# selesai/gagal, baris `self.signals.finished.emit(...)` atau
# `self.signals.error.emit(...)` akan gagal dengan
# "RuntimeError: Signal source has been deleted" - dan exception itu
# terjadi DI DALAM except block sehingga callback on_success/on_error
# TIDAK PERNAH terpanggil. Di GenericListPage, itu berarti
# `_set_write_buttons_enabled(True)` tidak pernah dipanggil lagi -> semua
# tombol tulis (Tambah/Ubah/Hapus/Aksi) macet permanen, walau Refresh
# (yang tidak lewat callback ini) masih terlihat jalan.
#
# Perbaikan: simpan referensi setiap worker yang sedang berjalan di set
# module-level ini sampai ia benar-benar selesai (finished ATAU error),
# baru dilepas. Ini menjamin objek (dan QObject sinyalnya) tidak akan
# di-garbage-collect sebelum event selesai/error-nya sempat di-emit dan
# diproses di main thread.
# ---------------------------------------------------------------------------
_active_workers: set[_Worker] = set()


def run_task(
    fn: Callable[..., Any],
    on_success: Callable[[Any], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    *args: Any,
    **kwargs: Any,
) -> _Worker:
    """Menjalankan `fn(*args, **kwargs)` di background thread."""
    worker = _Worker(fn, *args, **kwargs)
    _active_workers.add(worker)

    def _release(_ignored: Any = None) -> None:
        # Dipanggil setelah finished/error selesai diproses; baru boleh
        # melepas referensi supaya objek aman di-GC.
        _active_workers.discard(worker)

    if on_success:
        worker.signals.finished.connect(on_success)
    if on_error:
        worker.signals.error.connect(on_error)
    worker.signals.finished.connect(_release)
    worker.signals.error.connect(_release)

    _pool.start(worker)
    return worker
