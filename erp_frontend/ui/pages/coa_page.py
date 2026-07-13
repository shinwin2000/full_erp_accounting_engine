"""
ui/pages/coa_page.py
=====================
Bagan Akun (Chart of Accounts). Menampilkan struktur akun sebagai
QTreeWidget (dari endpoint /coa/chart-of-accounts/tree bila tersedia,
fallback ke /accounts + susun manual berdasarkan parent_account_code),
plus form tambah/ubah akun.
"""
from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.api_client import api_client
from core.formatting import extract_list, format_money
from core.workers import run_task
from registry.module_registry import FieldSpec, FieldType
from ui.widgets.form_dialog import FormDialog

BASE = "/coa/chart-of-accounts"

ACCOUNT_FIELDS = [
    FieldSpec("account_code", "Kode Akun", required=True),
    FieldSpec("account_name", "Nama Akun", required=True),
    FieldSpec("account_type", "Tipe Akun", FieldType.SELECT,
              choices=("asset", "liability", "equity", "revenue", "expense"), required=True),
    FieldSpec("normal_balance", "Saldo Normal", FieldType.SELECT, choices=("debit", "credit"), required=True),
    FieldSpec("parent_account_code", "Kode Induk (opsional)"),
    FieldSpec("category", "Kategori"),
    FieldSpec("currency_code", "Mata Uang", default="IDR"),
    FieldSpec("opening_balance", "Saldo Awal", FieldType.DECIMAL, default=0),
    FieldSpec("description", "Deskripsi", FieldType.TEXTAREA),
]


class CoaPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._accounts: list[dict[str, Any]] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        header = QHBoxLayout()
        title = QLabel("🌳  Bagan Akun (Chart of Accounts)")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        header.addWidget(title)
        header.addStretch()

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Cari kode/nama akun...")
        self.search_edit.setMaximumWidth(240)
        self.search_edit.textChanged.connect(self._apply_filter)
        header.addWidget(self.search_edit)

        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)

        new_btn = QPushButton("+ Akun Baru")
        new_btn.setObjectName("primaryButton")
        new_btn.clicked.connect(self._create_account)
        header.addWidget(new_btn)
        outer.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Kode / Nama Akun", "Tipe", "Saldo Normal", "Saldo"])
        self.tree.setColumnWidth(0, 320)
        self.tree.itemDoubleClicked.connect(self._on_edit_current)
        splitter.addWidget(self.tree)

        detail_panel = QWidget()
        detail_layout = QVBoxLayout(detail_panel)
        detail_title = QLabel("Detail Akun")
        detail_title.setStyleSheet("font-weight:700; font-size:14px;")
        detail_layout.addWidget(detail_title)
        self.detail_label = QLabel("Pilih akun untuk melihat detail.")
        self.detail_label.setWordWrap(True)
        self.detail_label.setAlignment(Qt.AlignTop)
        detail_layout.addWidget(self.detail_label, stretch=1)

        edit_btn = QPushButton("✎ Ubah Akun Terpilih")
        edit_btn.clicked.connect(self._on_edit_current)
        detail_layout.addWidget(edit_btn)
        splitter.addWidget(detail_panel)
        splitter.setSizes([600, 260])
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)

        outer.addWidget(splitter, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self.status_label.setText("Memuat bagan akun...")
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{BASE}/accounts", params={"page_size": 1000, "limit": 1000})

    def _on_loaded(self, payload: Any) -> None:
        self._accounts = extract_list(payload)
        self._render_tree(self._accounts)
        self.status_label.setText(f"{len(self._accounts)} akun dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _render_tree(self, accounts: list[dict[str, Any]]) -> None:
        self.tree.clear()
        by_code: dict[str, QTreeWidgetItem] = {}
        pending: list[dict[str, Any]] = []

        accounts_sorted = sorted(accounts, key=lambda a: str(a.get("account_code", "")))

        for acc in accounts_sorted:
            item = self._make_item(acc)
            code = str(acc.get("account_code", ""))
            by_code[code] = item
            parent_code = acc.get("parent_account_code")
            if parent_code and str(parent_code) in by_code:
                by_code[str(parent_code)].addChild(item)
            elif parent_code:
                pending.append(acc)  # parent belum diproses (urutan data)
            else:
                self.tree.addTopLevelItem(item)

        # retry untuk anak yang parent-nya muncul belakangan
        for acc in pending:
            code = str(acc.get("account_code", ""))
            parent_code = str(acc.get("parent_account_code"))
            item = by_code.get(code)
            if item is None:
                continue
            if parent_code in by_code:
                by_code[parent_code].addChild(item)
            else:
                self.tree.addTopLevelItem(item)

        self.tree.expandAll()

    def _make_item(self, acc: dict[str, Any]) -> QTreeWidgetItem:
        label = f"{acc.get('account_code', '')} — {acc.get('account_name', '')}"
        item = QTreeWidgetItem([
            label,
            str(acc.get("account_type", "") or ""),
            str(acc.get("normal_balance", "") or ""),
            format_money(acc.get("balance") or acc.get("opening_balance") or 0, acc.get("currency_code", "IDR")),
        ])
        item.setData(0, Qt.UserRole, acc)
        return item

    def _apply_filter(self, text: str) -> None:
        text = text.lower().strip()
        if not text:
            self._render_tree(self._accounts)
            return
        filtered = [
            a for a in self._accounts
            if text in str(a.get("account_code", "")).lower() or text in str(a.get("account_name", "")).lower()
        ]
        self._render_tree(filtered)

    # ------------------------------------------------------------------
    def _on_selection_changed(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            self.detail_label.setText("Pilih akun untuk melihat detail.")
            return
        acc = items[0].data(0, Qt.UserRole) or {}
        lines = [f"<b>{acc.get('account_code')} — {acc.get('account_name')}</b>", ""]
        for key in ("account_type", "normal_balance", "category", "currency_code", "description"):
            if acc.get(key):
                lines.append(f"<b>{key.replace('_', ' ').title()}:</b> {acc.get(key)}")
        self.detail_label.setText("<br>".join(lines))

    def _on_edit_current(self, *_args) -> None:
        items = self.tree.selectedItems()
        if not items:
            QMessageBox.information(self, "Info", "Pilih akun terlebih dahulu.")
            return
        acc = items[0].data(0, Qt.UserRole) or {}
        dlg = FormDialog("Ubah Akun", ACCOUNT_FIELDS, initial=acc, parent=self)
        if dlg.exec():
            payload = dlg.result_payload()
            code = acc.get("account_code")
            run_task(
                api_client.put,
                on_success=lambda _r: self._after_write("Akun diperbarui."),
                on_error=self._on_write_error,
                path=f"{BASE}/accounts/{code}",
                json_body=payload,
            )

    def _create_account(self) -> None:
        dlg = FormDialog("Akun Baru", ACCOUNT_FIELDS, parent=self)
        if dlg.exec():
            payload = dlg.result_payload()
            run_task(
                api_client.post,
                on_success=lambda _r: self._after_write("Akun baru ditambahkan."),
                on_error=self._on_write_error,
                path=f"{BASE}/accounts",
                json_body=payload,
            )

    def _after_write(self, message: str) -> None:
        self.status_label.setText(message)
        self.refresh()

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
