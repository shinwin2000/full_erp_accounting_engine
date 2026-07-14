"""
ui/login_window.py
===================
Layar login. Memanggil POST /api/v1/iam/login (lihat api_client.login).
Menangani MFA (kode 6 digit) dan pemilihan legal entity bila user
terhubung ke lebih dari satu entitas.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.api_client import ApiError, ConnectionFailedError, api_client
from core.config import APP_NAME, settings
from core.workers import run_task


class LoginWindow(QWidget):
    login_success = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Masuk — {APP_NAME}")
        self.resize(420, 560)
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignCenter)

        card = QFrame()
        card.setObjectName("card")
        card.setProperty("class", "card")
        card.setFixedWidth(380)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 32, 32, 32)
        card_layout.setSpacing(14)

        logo = QLabel("🏛️")
        logo.setAlignment(Qt.AlignCenter)
        logo.setFont(QFont("Segoe UI", 34))
        card_layout.addWidget(logo)

        title = QLabel("Sovereign ERP")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        card_layout.addWidget(title)

        subtitle = QLabel("Accounting Engine — Desktop Client")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color:#6B7280;")
        card_layout.addWidget(subtitle)
        card_layout.addSpacing(10)

        form = QFormLayout()
        form.setSpacing(10)

        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("Username atau email")
        form.addRow("Username", self.username_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("Password")
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.returnPressed.connect(self._do_login)
        form.addRow("Password", self.password_edit)

        self.mfa_edit = QLineEdit()
        self.mfa_edit.setPlaceholderText("Kode MFA (jika aktif)")
        self.mfa_edit.setMaxLength(6)
        form.addRow("Kode MFA", self.mfa_edit)

        card_layout.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color:#DC2626; font-size:12px;")
        self.error_label.setVisible(False)
        card_layout.addWidget(self.error_label)

        self.login_btn = QPushButton("Masuk")
        self.login_btn.setObjectName("primaryButton")
        self.login_btn.setMinimumHeight(38)
        self.login_btn.clicked.connect(self._do_login)
        card_layout.addWidget(self.login_btn)

        server_row = QHBoxLayout()
        server_label = QLabel("Server:")
        server_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        self.server_edit = QLineEdit(settings.api_base_url)
        self.server_edit.setStyleSheet("color:#9CA3AF; font-size:11px; border:none; background:transparent;")
        server_row.addWidget(server_label)
        server_row.addWidget(self.server_edit)
        card_layout.addLayout(server_row)

        outer.addWidget(card)

    # ------------------------------------------------------------------
    def _set_loading(self, loading: bool) -> None:
        self.login_btn.setEnabled(not loading)
        self.login_btn.setText("Memproses..." if loading else "Masuk")
        self.username_edit.setEnabled(not loading)
        self.password_edit.setEnabled(not loading)
        self.mfa_edit.setEnabled(not loading)

    def _do_login(self) -> None:
        settings.api_base_url = self.server_edit.text().strip() or settings.api_base_url
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        mfa = self.mfa_edit.text().strip() or None

        self.error_label.setVisible(False)
        if not username or not password:
            self._show_error("Username dan password wajib diisi.")
            return

        self._set_loading(True)
        run_task(
            api_client.login,
            on_success=self._on_login_success,
            on_error=self._on_login_error,
            username=username,
            password=password,
            mfa_code=mfa,
        )

    def _on_login_success(self, _data) -> None:
        self._set_loading(False)
        settings.save()
        self.login_success.emit()

    def _on_login_error(self, message: str) -> None:
        self._set_loading(False)
        if "422" in message and "mfa" in message.lower():
            self._show_error("Kode MFA diperlukan atau tidak valid.")
        else:
            self._show_error(message)

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)
