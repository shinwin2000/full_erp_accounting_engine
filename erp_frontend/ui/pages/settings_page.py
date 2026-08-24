"""
ui/pages/settings_page.py
============================
Pengaturan Sistem. Backend hanya menyediakan akses per-kategori/per-key
(tidak ada list global), jadi UI-nya: pilih kategori -> lihat daftar
setting -> ubah nilai per key.
Endpoint: /settings/settings/categories, /by-category/{cat}, /{key}

FIX: sebelumnya halaman ini hanya punya satu tombol ("Ubah Nilai Setting
Terpilih") walaupun backend (fastapi_system_settings_router.py) sudah
mendukung banyak fitur lain sejak lama: kunci/buka kunci setting,
aktifkan/nonaktifkan, reset ke default, lihat riwayat perubahan per
setting, lihat audit trail keseluruhan, serta export/import konfigurasi.
Semua fitur itu tidak pernah punya tombol di GUI ini. Ditambahkan di
bawah, satu tombol per fitur, plus badge status Aktif/Nonaktif/Terkunci
di setiap baris list supaya jelas kondisi setting saat ini.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from core.api_client import api_client
from core.formatting import extract_list
from core.workers import run_task
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

BASE = "/settings/settings"


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[dict[str, Any]] = []
        self._actions_busy = False
        self._build_ui()
        self._load_categories()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        header = QHBoxLayout()
        title = QLabel("⚙️  Pengaturan Sistem")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        header.addWidget(title)
        header.addStretch()

        self.category_combo = QComboBox()
        self.category_combo.setMinimumWidth(220)
        self.category_combo.currentTextChanged.connect(self._load_settings_for_category)
        header.addWidget(QLabel("Kategori:"))
        header.addWidget(self.category_combo)

        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self._load_categories)
        header.addWidget(refresh_btn)
        outer.addLayout(header)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._edit_setting)
        self.list_widget.currentItemChanged.connect(lambda *_: self._update_button_states())
        outer.addWidget(self.list_widget, stretch=1)

        # --- Row 1: aksi per-setting yang dipilih ---
        row1 = QHBoxLayout()
        edit_btn = QPushButton("✎ Ubah Nilai")
        edit_btn.clicked.connect(lambda: self._edit_setting(self.list_widget.currentItem()))
        row1.addWidget(edit_btn)

        self.lock_btn = QPushButton("🔒 Kunci")
        self.lock_btn.clicked.connect(self._lock_selected)
        row1.addWidget(self.lock_btn)

        self.unlock_btn = QPushButton("🔓 Buka Kunci")
        self.unlock_btn.clicked.connect(self._unlock_selected)
        row1.addWidget(self.unlock_btn)

        self.activate_btn = QPushButton("▶ Aktifkan")
        self.activate_btn.clicked.connect(self._activate_selected)
        row1.addWidget(self.activate_btn)

        self.deactivate_btn = QPushButton("⏸ Nonaktifkan")
        self.deactivate_btn.clicked.connect(self._deactivate_selected)
        row1.addWidget(self.deactivate_btn)

        self.reset_btn = QPushButton("↺ Reset ke Default")
        self.reset_btn.clicked.connect(self._reset_selected)
        row1.addWidget(self.reset_btn)

        self.history_btn = QPushButton("🕒 Riwayat")
        self.history_btn.clicked.connect(self._show_history)
        row1.addWidget(self.history_btn)
        outer.addLayout(row1)

        # --- Row 2: aksi tingkat sistem (tidak butuh setting terpilih) ---
        row2 = QHBoxLayout()
        audit_btn = QPushButton("📋 Audit Trail")
        audit_btn.clicked.connect(self._show_audit_trail)
        row2.addWidget(audit_btn)

        export_btn = QPushButton("⬇ Export Konfigurasi")
        export_btn.clicked.connect(self._export_settings)
        row2.addWidget(export_btn)

        import_btn = QPushButton("⬆ Import Konfigurasi")
        import_btn.clicked.connect(self._import_settings)
        row2.addWidget(import_btn)
        row2.addStretch()
        outer.addLayout(row2)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

        self._update_button_states()

    def _update_button_states(self) -> None:
        """Aktif/nonaktifkan tombol per-setting sesuai status setting yang
        sedang dipilih (mis. tombol Kunci disembunyikan kalau sudah
        terkunci), supaya user tidak memicu aksi yang pasti ditolak
        backend."""
        if self._actions_busy:
            return
        item = self.list_widget.currentItem()
        data = item.data(1000) if item else None
        has_selection = data is not None
        is_locked = bool(data.get("is_locked")) if data else False
        is_active = bool(data.get("is_active", True)) if data else True
        is_readonly = bool(data.get("is_readonly")) if data else False

        self.lock_btn.setEnabled(has_selection and not is_locked)
        self.unlock_btn.setEnabled(has_selection and is_locked)
        self.activate_btn.setEnabled(has_selection and not is_active)
        self.deactivate_btn.setEnabled(has_selection and is_active and not is_readonly)
        self.reset_btn.setEnabled(has_selection and not is_readonly and not is_locked)
        self.history_btn.setEnabled(has_selection)

    def _set_actions_busy(self, busy: bool) -> None:
        """FIX: sebelumnya tombol aksi (mis. Aktifkan) baru dinonaktifkan
        lewat _update_button_states() SETELAH daftar selesai dimuat ulang
        (perjalanan pulang-pergi request async). Selama jeda itu tombol
        masih bisa diklik, jadi klik cepat/berulang memicu banyak request
        yang sama beruntun (terlihat di log: satu klik "Aktifkan" memicu
        11 kali POST /activate berturut-turut). Sekarang tombol langsung
        dikunci begitu aksi mulai dijalankan, baru dilepas lagi setelah
        request selesai (sukses maupun gagal)."""
        self._actions_busy = busy
        for btn in (self.lock_btn, self.unlock_btn, self.activate_btn,
                    self.deactivate_btn, self.reset_btn, self.history_btn):
            btn.setEnabled(not busy)
        if not busy:
            self._update_button_states()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def _load_categories(self) -> None:
        self.status_label.setText("Memuat kategori...")
        run_task(api_client.get, on_success=self._on_categories, on_error=self._on_error, path=f"{BASE}/categories")

    def _on_categories(self, payload: Any) -> None:
        categories = extract_list(payload) or (payload if isinstance(payload, list) else [])
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        names = []
        for c in categories:
            names.append(c.get("name") if isinstance(c, dict) else str(c))
        self.category_combo.addItems(names or ["general"])
        self.category_combo.blockSignals(False)
        self.status_label.setText(f"{len(names)} kategori dimuat.")
        if names:
            self._load_settings_for_category(names[0])

    def _load_settings_for_category(self, category: str) -> None:
        if not category:
            return
        self.status_label.setText(f"Memuat setting kategori '{category}'...")
        run_task(api_client.get, on_success=self._on_settings, on_error=self._on_error,
                  path=f"{BASE}/by-category/{category}")

    def _on_settings(self, payload: Any) -> None:
        # FIX: sebelumnya seleksi baris SELALU hilang setelah reload
        # (list_widget.clear() menghapus current selection), termasuk
        # reload otomatis setelah aksi seperti lock/unlock/aktifkan/
        # nonaktifkan. Akibatnya setelah melakukan satu aksi, semua tombol
        # yang butuh baris terpilih (termasuk Reset dan Riwayat) langsung
        # ikut nonaktif walau user belum sengaja membatalkan pilihannya -
        # user harus klik ulang barisnya setiap kali. Sekarang key yang
        # sedang dipilih disimpan sebelum reload, lalu dicari & dipilih
        # ulang di daftar baru kalau masih ada.
        previously_selected_key = self._selected_key_silent()

        self._items = extract_list(payload)
        self.list_widget.clear()
        restore_row = -1
        for idx, item in enumerate(self._items):
            key = item.get("key", "")
            value = item.get("value", "")
            badges = []
            if not item.get("is_active", True):
                badges.append("Nonaktif")
            if item.get("is_locked"):
                badges.append("Terkunci")
            if item.get("is_readonly"):
                badges.append("Readonly")
            suffix = f"   [{', '.join(badges)}]" if badges else ""
            list_item = QListWidgetItem(f"{key}  =  {value}{suffix}")
            list_item.setData(1000, item)
            self.list_widget.addItem(list_item)
            if previously_selected_key and key == previously_selected_key:
                restore_row = idx
        if restore_row >= 0:
            self.list_widget.setCurrentRow(restore_row)
        self.status_label.setText(f"{len(self._items)} setting ditemukan.")
        # FIX: dipakai baik untuk reload biasa (Refresh/ganti kategori,
        # busy sudah False - ini sama saja dengan _update_button_states())
        # maupun sebagai titik pelepasan busy-lock setelah aksi mutasi
        # (activate/deactivate/lock/dst) selesai dan datanya sudah fresh
        # dari server - lihat _set_actions_busy().
        self._set_actions_busy(False)

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _after_write(self, message: str) -> None:
        self.status_label.setText(message)
        self._load_settings_for_category(self.category_combo.currentText())

    def _write_error(self, message: str) -> None:
        # FIX: kalau aksinya sendiri gagal (mis. server menolak), tidak ada
        # reload daftar yang akan melepas busy-lock - jadi harus dilepas
        # di sini juga, atau tombol aksi akan macet nonaktif selamanya.
        self._set_actions_busy(False)
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText(f"Gagal: {message}")

    def _selected_key_silent(self) -> str | None:
        """Sama seperti _selected_key() tapi tanpa popup - dipakai saat
        internal (mis. menyimpan key sebelum reload) di mana 'tidak ada
        yang dipilih' bukan kondisi yang perlu diberitahukan ke user."""
        item = self.list_widget.currentItem()
        if item is None:
            return None
        data = item.data(1000) or {}
        return data.get("key")

    def _selected_key(self) -> str | None:
        item = self.list_widget.currentItem()
        if item is None:
            QMessageBox.information(self, "Info", "Pilih setting terlebih dahulu.")
            return None
        data = item.data(1000) or {}
        return data.get("key")

    # ------------------------------------------------------------------
    # Ubah nilai
    # ------------------------------------------------------------------
    def _edit_setting(self, list_item: QListWidgetItem | None) -> None:
        if list_item is None:
            QMessageBox.information(self, "Info", "Pilih setting terlebih dahulu.")
            return
        data = list_item.data(1000) or {}
        dlg = _SettingEditDialog(data, parent=self)
        if dlg.exec():
            key = data.get("key")
            new_value, reason = dlg.new_value(), dlg.reason()
            # FIX: api_client.put() tidak punya parameter `params` (beda
            # dari .get/.post/.delete), sementara `reason` di endpoint PUT
            # ini adalah query param (Query("")) - jadi disisipkan manual
            # ke query string path, bukan lewat argumen params yang tidak
            # ada.
            path = f"{BASE}/{key}"
            if reason:
                path += f"?{urlencode({'reason': reason})}"
            run_task(
                api_client.put,
                on_success=lambda _r: self._after_write("Setting berhasil diperbarui."),
                on_error=self._write_error,
                path=path,
                json_body={"value": new_value},
            )

    # ------------------------------------------------------------------
    # Kunci / Buka Kunci
    # ------------------------------------------------------------------
    def _lock_selected(self) -> None:
        key = self._selected_key()
        if not key:
            return
        reason, ok = QInputDialog.getText(self, "Kunci Setting", f"Alasan mengunci '{key}' (opsional):")
        if not ok:
            return
        # FIX: `reason` di endpoint ini adalah query param (Query("")),
        # bukan body JSON - dikirim lewat `params`, bukan `json_body`.
        self._set_actions_busy(True)
        run_task(
            api_client.post,
            on_success=lambda _r: self._after_write(f"Setting '{key}' dikunci."),
            on_error=self._write_error,
            path=f"{BASE}/{key}/lock",
            params={"reason": reason or ""},
        )

    def _unlock_selected(self) -> None:
        key = self._selected_key()
        if not key:
            return
        reason, ok = QInputDialog.getText(self, "Buka Kunci Setting", f"Alasan membuka kunci '{key}' (opsional):")
        if not ok:
            return
        self._set_actions_busy(True)
        run_task(
            api_client.post,
            on_success=lambda _r: self._after_write(f"Kunci setting '{key}' dibuka."),
            on_error=self._write_error,
            path=f"{BASE}/{key}/unlock",
            params={"reason": reason or ""},
        )

    # ------------------------------------------------------------------
    # Aktifkan / Nonaktifkan
    # ------------------------------------------------------------------
    def _activate_selected(self) -> None:
        key = self._selected_key()
        if not key:
            return
        self._set_actions_busy(True)
        run_task(
            api_client.post,
            on_success=lambda _r: self._after_write(f"Setting '{key}' diaktifkan."),
            on_error=self._write_error,
            path=f"{BASE}/{key}/activate",
        )

    def _deactivate_selected(self) -> None:
        key = self._selected_key()
        if not key:
            return
        confirm = QMessageBox.question(self, "Konfirmasi", f"Nonaktifkan setting '{key}'?")
        if confirm != QMessageBox.Yes:
            return
        reason, ok = QInputDialog.getText(self, "Nonaktifkan Setting", "Alasan (opsional):")
        if not ok:
            return
        self._set_actions_busy(True)
        run_task(
            api_client.delete,
            on_success=lambda _r: self._after_write(f"Setting '{key}' dinonaktifkan."),
            on_error=self._write_error,
            path=f"{BASE}/{key}",
            params={"reason": reason or ""},
        )

    # ------------------------------------------------------------------
    # Reset ke default
    # ------------------------------------------------------------------
    def _reset_selected(self) -> None:
        key = self._selected_key()
        if not key:
            return
        confirm = QMessageBox.question(
            self, "Konfirmasi", f"Reset setting '{key}' ke nilai default? Nilai saat ini akan hilang."
        )
        if confirm != QMessageBox.Yes:
            return
        self._set_actions_busy(True)
        run_task(
            api_client.post,
            on_success=lambda _r: self._after_write(f"Setting '{key}' direset ke default."),
            on_error=self._write_error,
            path=f"{BASE}/{key}/reset",
        )

    # ------------------------------------------------------------------
    # Riwayat per setting
    # ------------------------------------------------------------------
    def _show_history(self) -> None:
        key = self._selected_key()
        if not key:
            return
        run_task(
            api_client.get,
            on_success=lambda payload: self._on_history(key, payload),
            on_error=self._write_error,
            path=f"{BASE}/{key}/history",
        )

    def _on_history(self, key: str, payload: Any) -> None:
        entries = extract_list(payload)
        dlg = _ReadOnlyListDialog(f"Riwayat: {key}", entries, self._format_history_entry, parent=self)
        dlg.exec()

    @staticmethod
    def _format_history_entry(entry: dict[str, Any]) -> str:
        when = entry.get("changed_at", "")
        old = entry.get("old_value")
        new = entry.get("new_value")
        by = entry.get("changed_by_name") or entry.get("changed_by") or "-"
        reason = entry.get("reason") or "-"
        return f"[{when}] {old} → {new}  (oleh: {by}, alasan: {reason})"

    # ------------------------------------------------------------------
    # Audit trail keseluruhan
    # ------------------------------------------------------------------
    def _show_audit_trail(self) -> None:
        run_task(
            api_client.get,
            on_success=self._on_audit_trail,
            on_error=self._write_error,
            path=f"{BASE}/audit",
        )

    def _on_audit_trail(self, payload: Any) -> None:
        entries = extract_list(payload)
        dlg = _ReadOnlyListDialog("Audit Trail", entries, self._format_history_entry, parent=self)
        dlg.exec()

    # ------------------------------------------------------------------
    # Export / Import
    # ------------------------------------------------------------------
    def _export_settings(self) -> None:
        run_task(
            api_client.get,
            on_success=self._on_export_ready,
            on_error=self._write_error,
            path=f"{BASE}/export",
            params={"format": "json"},
        )

    def _on_export_ready(self, payload: Any) -> None:
        # Backend mengembalikan payload JSON siap-unduh (list of settings).
        text = payload if isinstance(payload, str) else json.dumps(payload, indent=2, ensure_ascii=False)
        save_path, _ = QFileDialog.getSaveFileName(self, "Simpan Export Setting", "settings_export.json", "JSON (*.json)")
        if not save_path:
            return
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(text)
            self.status_label.setText(f"Konfigurasi diekspor ke {save_path}")
        except OSError as e:
            QMessageBox.warning(self, "Gagal", f"Tidak bisa menulis file: {e}")

    def _import_settings(self) -> None:
        open_path, _ = QFileDialog.getOpenFileName(self, "Pilih File Import Setting", "", "JSON (*.json)")
        if not open_path:
            return
        try:
            with open(open_path, encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            QMessageBox.warning(self, "Gagal", f"Tidak bisa membaca file: {e}")
            return

        confirm = QMessageBox.question(
            self, "Konfirmasi", "Import akan membuat setting baru dan memperbarui setting yang sudah ada. Lanjutkan?"
        )
        if confirm != QMessageBox.Yes:
            return

        run_task(
            api_client.post,
            on_success=self._on_import_done,
            on_error=self._write_error,
            path=f"{BASE}/import",
            json_body={"data": content, "format": "json", "mode": "merge"},
        )

    def _on_import_done(self, payload: Any) -> None:
        imported = payload.get("imported_count", 0) if isinstance(payload, dict) else 0
        updated = payload.get("updated_count", 0) if isinstance(payload, dict) else 0
        skipped = payload.get("skipped_count", 0) if isinstance(payload, dict) else 0
        errors = payload.get("errors", []) if isinstance(payload, dict) else []
        msg = f"Import selesai: {imported} baru, {updated} diperbarui, {skipped} dilewati."
        if errors:
            msg += f"\n\n{len(errors)} error:\n" + "\n".join(str(e) for e in errors[:10])
        QMessageBox.information(self, "Import Selesai", msg)
        self._load_settings_for_category(self.category_combo.currentText())


class _SettingEditDialog(QDialog):
    def __init__(self, data: dict[str, Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Ubah Setting: {data.get('key', '')}")
        self.resize(420, 260)
        outer = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Key", QLabel(str(data.get("key", ""))))
        self.value_edit = QTextEdit()
        self.value_edit.setPlainText(str(data.get("value", "")))
        self.value_edit.setFixedHeight(90)
        form.addRow("Value", self.value_edit)
        self.reason_edit = QTextEdit()
        self.reason_edit.setFixedHeight(50)
        self.reason_edit.setPlaceholderText("Opsional - untuk audit trail")
        form.addRow("Alasan", self.reason_edit)
        outer.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Simpan")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def new_value(self) -> str:
        return self.value_edit.toPlainText().strip()

    def reason(self) -> str:
        return self.reason_edit.toPlainText().strip()


class _ReadOnlyListDialog(QDialog):
    """Dialog generik untuk menampilkan daftar read-only (riwayat / audit
    trail) — dipakai baik oleh tombol Riwayat maupun tombol Audit Trail."""

    def __init__(self, title: str, entries: list[dict[str, Any]], formatter, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 420)
        outer = QVBoxLayout(self)

        list_widget = QListWidget()
        if entries:
            for entry in entries:
                text = formatter(entry) if isinstance(entry, dict) else str(entry)
                list_widget.addItem(QListWidgetItem(text))
        else:
            placeholder = QListWidgetItem("Tidak ada data.")
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemIsEnabled)
            list_widget.addItem(placeholder)
        outer.addWidget(list_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        outer.addWidget(buttons)
