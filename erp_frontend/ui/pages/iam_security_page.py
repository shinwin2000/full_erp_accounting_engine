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

from core.api_client import api_client
from core.formatting import extract_list, format_datetime
from core.session import session
from core.workers import run_task
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False

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
        self.status_label.setWordWrap(True)
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
        # FIX: sebelumnya semua konten tab ini (QR code, hasil setup,
        # form verifikasi, form nonaktifkan MFA) ditumpuk langsung di
        # widget tanpa scroll area - di layar/resolusi yang lebih kecil,
        # bagian bawah (form "Nonaktifkan MFA") kepotong di luar batas
        # layar dan tidak bisa dijangkau sama sekali. Sekarang dibungkus
        # QScrollArea supaya selalu bisa di-scroll untuk menjangkau semua
        # bagian, apapun ukuran layarnya.
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        # Cuma izinkan scroll VERTIKAL - konten harus selalu muat mengikuti
        # lebar layar (word-wrap di semua label sudah memastikan itu), jadi
        # scroll horizontal tidak seharusnya pernah muncul lagi.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root_layout.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        outer = QVBoxLayout(content)
        instructions_label = QLabel(
            "<b>Setup MFA (Google Authenticator / Authy)</b><br>"
            "<span style='color:#6B7280;'>Langkah 1: klik Setup untuk dapat kode rahasia & QR code. "
            "Langkah 2: <b>scan QR code di bawah pakai kamera aplikasi authenticator di HP Anda</b> "
            "(bukan dengan cara diklik/dibuka di browser - link \"otpauth://...\" tidak bisa dibuka "
            "langsung di PC, itu format khusus untuk di-scan atau diketik manual ke aplikasi authenticator). "
            "Langkah 3: masukkan kode 6-digit untuk verifikasi.</span>"
        )
        # FIX BUG: sebelumnya label ini tidak di-word-wrap, jadi Qt
        # melebarkan seluruh teks jadi satu baris super panjang, memaksa
        # seluruh halaman (termasuk tombol "Nonaktifkan MFA" di bawahnya)
        # ikut melebar keluar layar dan butuh di-scroll ke KANAN untuk
        # dibaca. setWordWrap(True) bikin teks membungkus ke baris
        # berikutnya sesuai lebar yang tersedia, jadi halaman tetap
        # muat 1 layar (cuma scroll vertikal kalau perlu, tidak horizontal).
        instructions_label.setWordWrap(True)
        outer.addWidget(instructions_label)
        setup_btn = QPushButton("🔑 Setup MFA")
        setup_btn.setObjectName("primaryButton")
        setup_btn.clicked.connect(self._setup)
        outer.addWidget(setup_btn)

        self.qr_label = QLabel("")
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setFixedSize(200, 200)
        self.qr_label.setStyleSheet("background-color: white; border: 1px solid #E5E7EB;")
        outer.addWidget(self.qr_label, alignment=Qt.AlignCenter)

        self.setup_result = QTextEdit()
        self.setup_result.setReadOnly(True)
        self.setup_result.setFixedHeight(110)
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
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

    def _setup(self) -> None:
        run_task(api_client.post, on_success=self._on_setup_result, on_error=self._on_error, path=f"{BASE}/mfa/setup")

    def _on_setup_result(self, data: Any) -> None:
        data = data or {}
        backup_codes = data.get("backup_codes", [])
        qr_code_url = data.get("qr_code_url", "")

        # PENTING: qr_code_url berformat "otpauth://..." - ini BUKAN link
        # web biasa, jadi memang tidak bisa/tidak seharusnya diklik atau
        # dibuka di browser (tidak ada handler untuk skema "otpauth://" di
        # PC/browser biasa). Ini format standar TOTP yang cuma dikenali oleh
        # aplikasi authenticator (Google Authenticator, Authy, Microsoft
        # Authenticator, dll) - caranya: SCAN sebagai QR code pakai kamera
        # HP, atau ketik manual "Secret Key"-nya ke aplikasi authenticator.
        if HAS_QRCODE and qr_code_url:
            try:
                # FIX BUG: sebelumnya box_size=6, border=2 - border=2 di
                # BAWAH standar minimum QR code (ISO/IEC 18004 mewajibkan
                # "quiet zone" minimal 4 modul di sekeliling kode). Dengan
                # quiet zone terlalu tipis + background aplikasi berwarna
                # (bukan putih polos), banyak aplikasi scanner kamera HP
                # gagal mendeteksi pola finder QR-nya sama sekali - itu
                # sebabnya QR tidak bisa di-scan walau gambarnya kelihatan
                # normal di layar. box_size juga dinaikkan (6->10) supaya
                # tiap modul lebih besar/tajam saat difoto dari jarak HP.
                img = qrcode.make(qr_code_url, box_size=10, border=4)
                from io import BytesIO
                buf = BytesIO()
                img.save(buf, format="PNG")
                pixmap = QPixmap()
                pixmap.loadFromData(buf.getvalue(), "PNG")
                # FIX BUG: sebelumnya QLabel cuma di-set TINGGI tetap tanpa
                # lebar tetap, dan pixmap TIDAK di-scale sama sekali - QLabel
                # secara default menampilkan pixmap di ukuran ASLI-nya dan
                # MEMOTONG bagian yang melebihi batas label. Gambar QR
                # 490x490px jadi terpotong di dalam label yang lebih kecil,
                # bisa membuang sebagian pola QR (termasuk berpotensi
                # "finder pattern" di pojok yang wajib ada untuk terdeteksi
                # kamera) - ini kemungkinan besar penyebab utama QR tidak
                # bisa di-scan sama sekali. Sekarang di-scale proporsional
                # (KeepAspectRatio) supaya seluruh QR selalu utuh terlihat.
                scaled = pixmap.scaled(
                    self.qr_label.width(), self.qr_label.height(),
                    Qt.KeepAspectRatio, Qt.SmoothTransformation,
                )
                self.qr_label.setPixmap(scaled)
            except Exception:
                self.qr_label.setText("(gagal membuat gambar QR - masukkan Secret Key di bawah secara manual)")
        elif not HAS_QRCODE:
            self.qr_label.setText(
                "(package 'qrcode' belum terpasang di frontend - jalankan `pip install qrcode[pil]`\n"
                "untuk bisa lihat QR code. Sementara itu, masukkan Secret Key di bawah secara manual\n"
                "ke aplikasi authenticator Anda.)"
            )

        lines = [
            f"Secret Key (masukkan manual kalau tidak bisa scan QR): {data.get('secret_key', '')}",
            "",
            "Backup Codes (simpan di tempat aman, masing-masing hanya bisa dipakai sekali):",
        ] + [f"  - {c}" for c in backup_codes]
        self.setup_result.setPlainText("\n".join(lines))
        self.status_label.setText("Scan QR code di atas (atau masukkan Secret Key manual) ke aplikasi authenticator, lalu verifikasi di bawah.")

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
        self.status_label.setWordWrap(True)
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
        self.status_label.setWordWrap(True)
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
