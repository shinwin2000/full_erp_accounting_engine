"""
core/logging_setup.py
========================
Logging untuk lingkungan produksi. Semua error (termasuk exception tak
tertangani di UI thread) dicatat ke file rotating di
`~/.sovereign_erp/logs/app.log`, supaya user bisa mengirim log ini saat
lapor bug tanpa perlu reproduce masalahnya secara langsung.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
import traceback
from pathlib import Path

LOG_DIR = Path.home() / ".sovereign_erp" / "logs"
LOG_FILE = LOG_DIR / "app.log"

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """Panggil sekali di awal main.py sebelum QApplication dibuat."""
    global _configured
    if _configured:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Tangkap semua exception tak tertangani (termasuk di luar Qt event loop)
    def _log_uncaught_exception(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        root_logger.critical(
            "Uncaught exception:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )

    sys.excepthook = _log_uncaught_exception

    _configured = True
    root_logger.info("=" * 60)
    root_logger.info("Sovereign ERP Desktop — logging diaktifkan. Log file: %s", LOG_FILE)
    root_logger.info("=" * 60)


def install_qt_message_handler() -> None:
    """Redirect pesan warning/error internal Qt (mis. dari widget) ke logger."""
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:
        return

    logger = logging.getLogger("qt")

    def handler(msg_type, context, message):
        if msg_type == QtMsgType.QtWarningMsg:
            logger.warning(message)
        elif msg_type in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            logger.error(message)
        # QtDebugMsg/QtInfoMsg diabaikan supaya log tidak terlalu ramai

    qInstallMessageHandler(handler)
