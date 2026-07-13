"""
ui/pages/settings_page.py
============================
Pengaturan Sistem. Backend hanya menyediakan akses per-kategori/per-key
(tidak ada list global), jadi UI-nya: pilih kategori -> lihat daftar
setting -> ubah nilai per key.
Endpoint: /settings/settings/categories, /by-category/{cat}, /{key}
"""
from __future__ import annotations

from typing import Any, Optional

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.api_client import api_client
from core.formatting import extract_list
from core.workers import run_task

BASE = "/settings/settings"


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[dict[str, Any]] = []
        self._build_ui()
        self._load_categories()

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
        outer.addWidget(self.list_widget, stretch=1)

        edit_btn = QPushButton("✎ Ubah Nilai Setting Terpilih")
        edit_btn.clicked.connect(lambda: self._edit_setting(self.list_widget.currentItem()))
        outer.addWidget(edit_btn)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

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
        self._items = extract_list(payload)
        self.list_widget.clear()
        for item in self._items:
            key = item.get("key", "")
            value = item.get("value", "")
            list_item = QListWidgetItem(f"{key}  =  {value}")
            list_item.setData(1000, item)
            self.list_widget.addItem(list_item)
        self.status_label.setText(f"{len(self._items)} setting ditemukan.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _edit_setting(self, list_item: Optional[QListWidgetItem]) -> None:
        if list_item is None:
            QMessageBox.information(self, "Info", "Pilih setting terlebih dahulu.")
            return
        data = list_item.data(1000) or {}
        dlg = _SettingEditDialog(data, parent=self)
        if dlg.exec():
            key = data.get("key")
            new_value = dlg.new_value()
            run_task(
                api_client.put,
                on_success=lambda _r: self._after_write("Setting berhasil diperbarui."),
                on_error=lambda m: QMessageBox.warning(self, "Gagal", m),
                path=f"{BASE}/{key}",
                json_body={"value": new_value},
            )

    def _after_write(self, message: str) -> None:
        self.status_label.setText(message)
        self._load_settings_for_category(self.category_combo.currentText())


class _SettingEditDialog(QDialog):
    def __init__(self, data: dict[str, Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Ubah Setting: {data.get('key', '')}")
        self.resize(420, 220)
        outer = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Key", QLabel(str(data.get("key", ""))))
        self.value_edit = QTextEdit()
        self.value_edit.setPlainText(str(data.get("value", "")))
        self.value_edit.setFixedHeight(90)
        form.addRow("Value", self.value_edit)
        outer.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Simpan")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def new_value(self) -> str:
        return self.value_edit.toPlainText().strip()
