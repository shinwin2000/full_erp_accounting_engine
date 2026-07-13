#!/usr/bin/env python3
"""
main.py
========
Entry point aplikasi desktop Sovereign ERP (PySide6).

Jalankan dengan:
    python main.py

Konfigurasi server API bisa diubah lewat environment variable
ERP_API_BASE_URL, lewat kolom "Server" di layar login, atau dengan
mengedit ~/.sovereign_erp/config.ini setelah aplikasi pernah dijalankan.
"""
from __future__ import annotations

import sys

from core.config import APP_NAME, APP_ORG
from PySide6.QtWidgets import QApplication
from ui.login_window import LoginWindow
from ui.main_window import MainWindow
from ui.theme import QSS


class Application:
    """Mengelola transisi Login <-> MainWindow di dalam satu proses Qt."""

    def __init__(self) -> None:
        self.app = QApplication(sys.argv)
        self.app.setApplicationName(APP_NAME)
        self.app.setOrganizationName(APP_ORG)
        self.app.setStyleSheet(QSS)

        self.login_window: LoginWindow | None = None
        self.main_window: MainWindow | None = None

        self._show_login()

    # ------------------------------------------------------------------
    def _show_login(self) -> None:
        if self.main_window is not None:
            self.main_window.close()
            self.main_window = None

        self.login_window = LoginWindow()
        self.login_window.login_success.connect(self._show_main_window)
        self.login_window.show()

    def _show_main_window(self) -> None:
        if self.login_window is not None:
            self.login_window.close()
            self.login_window = None

        self.main_window = MainWindow()
        self.main_window.logout_requested.connect(self._show_login)
        self.main_window.show()

    def run(self) -> int:
        return self.app.exec()


def main() -> int:
    application = Application()
    return application.run()


if __name__ == "__main__":
    sys.exit(main())
