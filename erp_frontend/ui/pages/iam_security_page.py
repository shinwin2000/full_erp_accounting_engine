"""
ui/pages/iam_security_page.py
================================
Melengkapi gap di modul IAM: Manajemen sesi login, setup MFA (Multi-Factor
Authentication), monitoring percobaan login, dan ganti password —
self-service security untuk user yang sedang login.

Endpoint backend (base: /iam/iam):
  POST /change-password, /forgot-password, /reset-password
  POST /mfa/setup, /mfa/verify, /mfa/disable
  GET  /sessions, DELETE /sessions/{id}, DELETE /sessions (revoke all lain)
  GET  /login-attempts (admin)
"""
from __future__ import annotations

from typing import Any

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.api_client import api_client
from core.formatting import extract_list, format_datetime
from core.session import session
from core.workers import run_task

BASE = "/iam/iam"


class IamSecurityPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel("🔐  Keamanan Akun: Sesi, MFA & Password")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(SessionsTab(), "Sesi Login Aktif")
        self.tabs.addTab(MfaTab(), "MFA (Autentikasi 2 Langkah)")
        self.tabs.addTab(PasswordTab(), "Ganti Password")
        self.tabs.addTab(LoginAttemptsTab(), "Riwayat Percobaan Login (Admin)")
        outer.addWidget(self.tabs, stretch=1)


# ==========================================================================
class SessionsTab(QWidget):
    def __init__(self):
        super().__init__()
        self._records: list[dict[str, Any]] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        row = QHBoxLayout()
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self.refresh)
        row.addWidget(refresh_btn)
        row.addStretch()
        revoke_all_btn = QPushButton("🔒 Revoke Semua Sesi Lain")
        revoke_all_btn.setProperty("class", "danger")
        revoke_all_btn.clicked.connect(self._revoke_all)
        row.addWidget(revoke_all_btn)
        outer.addLayout(row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["IP Address", "Device/Browser", "Login Terakhir", "Kadaluarsa", "Status"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        outer.addWidget(self.table, stretch=1)

        revoke_btn = QPushButton("✘ Revoke Sesi Terpilih")
        revoke_btn.clicked.connect(self._revoke_selected)
        outer.addWidget(revoke_btn)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error, path=f"{BASE}/sessions")

    def _on_loaded(self, payload: Any) -> None:
        self._records = extract_list(payload)
        self.table.setRowCount(len(self._records))
        for r, s in enumerate(self._records):
            active = s.get("is_active") and not s.get("is_revoked")
            values = [
                s.get("ip_address", "") or "-",
                s.get("user_agent", "") or s.get("device_id", "") or "-",
                format_datetime(s.get("last_accessed_at")),
                format_datetime(s.get("expires_at")),
                "Aktif" if active else "Berakhir/Revoked",
            ]
            for c, v in enumerate(values):
                item = QTableWidgetItem(v)
                if c == 4:
                    item.setForeground(QColor("#059669" if active else "#9CA3AF"))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(self._records)} sesi ditemukan.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _revoke_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._records):
            QMessageBox.information(self, "Info", "Pilih sesi terlebih dahulu.")
            return
        sid = self._records[row].get("id")
        confirm = QMessageBox.question(self, "Konfirmasi", "Revoke sesi ini?")
        if confirm != QMessageBox.Yes:
            return
        run_task(api_client.delete, on_success=lambda _r: self._after("Sesi di-revoke."),
                  on_error=self._on_write_error, path=f"{BASE}/sessions/{sid}")

    def _revoke_all(self) -> None:
        confirm = QMessageBox.question(self, "Konfirmasi", "Revoke SEMUA sesi lain (kecuali sesi ini)?")
        if confirm != QMessageBox.Yes:
            return
        run_task(api_client.delete, on_success=lambda _r: self._after("Semua sesi lain di-revoke."),
                  on_error=self._on_write_error, path=f"{BASE}/sessions")

    def _after(self, msg: str) -> None:
        self.status_label.setText(msg)
        self.refresh()

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class MfaTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "<b>Setup MFA (Google Authenticator / Authy)</b><br>"
            "<span style='color:#6B7280;'>Langkah 1: klik Setup untuk dapat kode rahasia & QR code. "
            "Langkah 2: scan dengan aplikasi authenticator, lalu masukkan kode 6-digit untuk verifikasi.</span>"
        ))
        setup_btn = QPushButton("🔑 Setup MFA")
        setup_btn.setObjectName("primaryButton")
        setup_btn.clicked.connect(self._setup)
        outer.addWidget(setup_btn)

        self.setup_result = QTextEdit()
        self.setup_result.setReadOnly(True)
        self.setup_result.setFixedHeight(140)
        outer.addWidget(self.setup_result)

        verify_row = QHBoxLayout()
        self.verify_code_edit = QLineEdit()
        self.verify_code_edit.setPlaceholderText("Kode 6-digit dari aplikasi authenticator")
        self.verify_code_edit.setMaxLength(6)
        verify_row.addWidget(self.verify_code_edit)
        verify_btn = QPushButton("✔ Verifikasi & Aktifkan")
        verify_btn.setProperty("class", "success")
        verify_btn.clicked.connect(self._verify)
        verify_row.addWidget(verify_btn)
        outer.addLayout(verify_row)

        outer.addWidget(QLabel("<b>Nonaktifkan MFA</b>"))
        disable_form = QFormLayout()
        self.disable_password_edit = QLineEdit()
        self.disable_password_edit.setEchoMode(QLineEdit.Password)
        disable_form.addRow("Password Saat Ini", self.disable_password_edit)
        self.disable_code_edit = QLineEdit()
        self.disable_code_edit.setPlaceholderText("opsional jika MFA masih aktif")
        disable_form.addRow("Kode MFA", self.disable_code_edit)
        outer.addLayout(disable_form)
        disable_btn = QPushButton("🚫 Nonaktifkan MFA")
        disable_btn.setProperty("class", "danger")
        disable_btn.clicked.connect(self._disable)
        outer.addWidget(disable_btn)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _setup(self) -> None:
        run_task(api_client.post, on_success=self._on_setup_result, on_error=self._on_error, path=f"{BASE}/mfa/setup")

    def _on_setup_result(self, data: Any) -> None:
        data = data or {}
        backup_codes = data.get("backup_codes", [])
        lines = [
            f"Secret Key: {data.get('secret_key', '')}",
            f"QR Code URL: {data.get('qr_code_url', '')}",
            "",
            "Backup Codes (simpan di tempat aman):",
        ] + [f"  - {c}" for c in backup_codes]
        self.setup_result.setPlainText("\n".join(lines))
        self.status_label.setText("Scan QR code / masukkan secret key ke aplikasi authenticator, lalu verifikasi di bawah.")

    def _verify(self) -> None:
        code = self.verify_code_edit.text().strip()
        if len(code) != 6:
            QMessageBox.warning(self, "Validasi", "Kode MFA harus 6 digit.")
            return
        run_task(api_client.post, on_success=self._on_verify_result, on_error=self._on_error,
                  path=f"{BASE}/mfa/verify", json_body={"code": code})

    def _on_verify_result(self, data: Any) -> None:
        enabled = (data or {}).get("enabled", False)
        self.status_label.setText("MFA berhasil diaktifkan!" if enabled else "Kode salah, MFA belum aktif.")

    def _disable(self) -> None:
        if not self.disable_password_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "Password wajib diisi untuk nonaktifkan MFA.")
            return
        confirm = QMessageBox.question(self, "Konfirmasi", "Nonaktifkan MFA? Akun akan lebih rentan.")
        if confirm != QMessageBox.Yes:
            return
        payload = {
            "password": self.disable_password_edit.text(),
            "mfa_code": self.disable_code_edit.text().strip() or None,
        }
        run_task(api_client.post, on_success=lambda _r: self.status_label.setText("MFA dinonaktifkan."),
                  on_error=self._on_error, path=f"{BASE}/mfa/disable", json_body=payload)

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class PasswordTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(f"<b>Ganti Password untuk: {session.display_name}</b>"))
        form = QFormLayout()
        self.old_password_edit = QLineEdit()
        self.old_password_edit.setEchoMode(QLineEdit.Password)
        form.addRow("Password Lama", self.old_password_edit)
        self.new_password_edit = QLineEdit()
        self.new_password_edit.setEchoMode(QLineEdit.Password)
        form.addRow("Password Baru", self.new_password_edit)
        self.confirm_password_edit = QLineEdit()
        self.confirm_password_edit.setEchoMode(QLineEdit.Password)
        form.addRow("Ulangi Password Baru", self.confirm_password_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("💾 Ganti Password")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        outer.addWidget(submit_btn)

        outer.addWidget(QLabel("<b>Lupa Password (Kirim Link Reset ke Email)</b>"))
        forgot_row = QHBoxLayout()
        self.forgot_email_edit = QLineEdit()
        self.forgot_email_edit.setPlaceholderText("Email terdaftar")
        forgot_row.addWidget(self.forgot_email_edit)
        forgot_btn = QPushButton("Kirim Link Reset")
        forgot_btn.clicked.connect(self._forgot)
        forgot_row.addWidget(forgot_btn)
        outer.addLayout(forgot_row)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _submit(self) -> None:
        if len(self.new_password_edit.text()) < 8:
            QMessageBox.warning(self, "Validasi", "Password baru minimal 8 karakter.")
            return
        if self.new_password_edit.text() != self.confirm_password_edit.text():
            QMessageBox.warning(self, "Validasi", "Konfirmasi password tidak cocok.")
            return
        payload = {"old_password": self.old_password_edit.text(), "new_password": self.new_password_edit.text()}
        run_task(api_client.post, on_success=lambda _r: self.status_label.setText("Password berhasil diganti."),
                  on_error=self._on_error, path=f"{BASE}/change-password", json_body=payload)

    def _forgot(self) -> None:
        if not self.forgot_email_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "Email wajib diisi.")
            return
        run_task(api_client.post, on_success=lambda _r: self.status_label.setText("Link reset password terkirim (jika email terdaftar)."),
                  on_error=self._on_error, path=f"{BASE}/forgot-password",
                  json_body={"email": self.forgot_email_edit.text().strip()})

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class LoginAttemptsTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        row = QHBoxLayout()
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self.refresh)
        row.addWidget(refresh_btn)
        row.addStretch()
        outer.addLayout(row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Waktu", "Username", "IP Address", "Berhasil", "Alasan Gagal"])
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{BASE}/login-attempts", params={"page_size": 100})

    def _on_loaded(self, payload: Any) -> None:
        rows = extract_list(payload)
        self.table.setRowCount(len(rows))
        for r, a in enumerate(rows):
            success = a.get("is_successful", a.get("success", False))
            values = [
                format_datetime(a.get("attempted_at", a.get("created_at"))),
                a.get("username", ""),
                a.get("ip_address", "") or "-",
                "Ya" if success else "Tidak",
                a.get("failure_reason", "") or "-",
            ]
            for c, v in enumerate(values):
                item = QTableWidgetItem(v)
                if c == 3:
                    item.setForeground(QColor("#059669" if success else "#DC2626"))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self.status_label.setText(f"{len(rows)} percobaan login ditemukan.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat (mungkin butuh hak admin): {message}")
