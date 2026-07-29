"""
ui/pages/coa_page.py
=====================
Bagan Akun (Chart of Accounts). Menampilkan struktur akun sebagai
QTreeWidget, dengan warna per tipe akun, ringkasan saldo per kategori,
tambah/ubah/hapus akun, dan pembuatan sub-akun cepat.

PERBAIKAN PENTING: endpoint update/delete backend pakai `{account_id}`
(UUID kolom `id`), BUKAN `account_code` — versi sebelumnya salah pakai
account_code sebagai path param yang akan selalu gagal (404) di backend
sungguhan. Sudah diperbaiki di sini.
"""
from __future__ import annotations

from typing import Any

from core.api_client import api_client
from core.formatting import extract_list, format_money
from core.workers import run_task
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
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
from registry.module_registry import FieldSpec, FieldType
from ui.widgets.form_dialog import FormDialog
from ui.widgets.kpi_card import KpiCard

BASE = "/coa/chart-of-accounts"

# Field untuk BUAT akun baru (semua field, termasuk yang tidak bisa diubah lagi setelah dibuat)
CREATE_FIELDS = [
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

# Field untuk UBAH akun (account_code/account_type/normal_balance TIDAK bisa
# diubah lagi setelah akun dibuat — sesuai AccountUpdateSchema backend, ini
# masuk akal secara akuntansi karena mengubah sifat dasar akun yang sudah
# dipakai transaksi akan merusak integritas laporan).
EDIT_FIELDS = [
    FieldSpec("account_name", "Nama Akun", required=True),
    FieldSpec("status", "Status", FieldType.SELECT,
              choices=("active", "inactive", "suspended", "locked", "archived")),
    FieldSpec("parent_account_code", "Kode Induk (opsional)"),
    FieldSpec("category", "Kategori"),
    FieldSpec("currency_code", "Mata Uang"),
    FieldSpec("is_bank_account", "Akun Bank", FieldType.BOOL, default=False),
    FieldSpec("is_cash_account", "Akun Kas", FieldType.BOOL, default=False),
    FieldSpec("is_intercompany", "Akun Intercompany", FieldType.BOOL, default=False),
    FieldSpec("budget_control", "Kontrol Budget", FieldType.BOOL, default=False),
    FieldSpec("description", "Deskripsi", FieldType.TEXTAREA),
]

TYPE_COLORS = {
    "asset": "#2563EB",
    "liability": "#DC2626",
    "equity": "#7C3AED",
    "revenue": "#059669",
    "expense": "#D97706",
}


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
        new_btn.clicked.connect(lambda: self._create_account(parent_code=None))
        header.addWidget(new_btn)
        outer.addLayout(header)

        # Ringkasan saldo per tipe akun
        self.summary_row = QHBoxLayout()
        self.summary_cards: dict[str, KpiCard] = {}
        for acc_type, label in [
            ("asset", "Total Aset"), ("liability", "Total Kewajiban"),
            ("equity", "Total Ekuitas"), ("revenue", "Total Pendapatan"), ("expense", "Total Beban"),
        ]:
            card = KpiCard(label, color=TYPE_COLORS[acc_type])
            self.summary_cards[acc_type] = card
            self.summary_row.addWidget(card)
        outer.addLayout(self.summary_row)

        splitter = QSplitter(Qt.Horizontal)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Kode / Nama Akun", "Tipe", "Saldo Normal", "Status", "Saldo"])
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

        add_child_btn = QPushButton("+ Tambah Sub-Akun")
        add_child_btn.clicked.connect(self._create_child_account)
        detail_layout.addWidget(add_child_btn)

        edit_btn = QPushButton("✎ Ubah Akun Terpilih")
        edit_btn.clicked.connect(self._on_edit_current)
        detail_layout.addWidget(edit_btn)

        delete_btn = QPushButton("🗑 Hapus/Nonaktifkan Akun")
        delete_btn.setProperty("class", "danger")
        delete_btn.clicked.connect(self._delete_current)
        detail_layout.addWidget(delete_btn)

        splitter.addWidget(detail_panel)
        splitter.setSizes([620, 260])
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
        self._render_summary(self._accounts)
        self.status_label.setText(f"{len(self._accounts)} akun dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _render_summary(self, accounts: list[dict[str, Any]]) -> None:
        totals: dict[str, float] = {}
        for acc in accounts:
            acc_type = str(acc.get("account_type", "")).lower()
            balance = acc.get("balance")
            if balance is None:
                balance = acc.get("opening_balance") or 0
            try:
                totals[acc_type] = totals.get(acc_type, 0) + float(balance)
            except (TypeError, ValueError):
                pass
        for acc_type, card in self.summary_cards.items():
            card.set_value(format_money(totals.get(acc_type, 0)))

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
        acc_type = str(acc.get("account_type", "") or "")
        status = str(acc.get("status", "") or "")
        item = QTreeWidgetItem([
            label,
            acc_type,
            str(acc.get("normal_balance", "") or ""),
            status,
            format_money(acc.get("balance") or acc.get("opening_balance") or 0, acc.get("currency_code", "IDR")),
        ])
        color = TYPE_COLORS.get(acc_type.lower())
        if color:
            for col in range(item.columnCount()):
                item.setForeground(col, QColor(color))
        if status.lower() in ("inactive", "suspended", "locked", "archived"):
            font = item.font(0)
            font.setItalic(True)
            for col in range(item.columnCount()):
                item.setFont(col, font)
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
        for key in ("account_type", "normal_balance", "status", "category", "currency_code", "description"):
            if acc.get(key):
                lines.append(f"<b>{key.replace('_', ' ').title()}:</b> {acc.get(key)}")
        flags = [f for f in ("is_bank_account", "is_cash_account", "is_intercompany", "budget_control") if acc.get(f)]
        if flags:
            lines.append(f"<b>Flag:</b> {', '.join(f.replace('is_', '').replace('_', ' ') for f in flags)}")
        self.detail_label.setText("<br>".join(lines))

    def _selected_account(self) -> dict[str, Any] | None:
        items = self.tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, Qt.UserRole) or {}

    def _on_edit_current(self, *_args) -> None:
        acc = self._selected_account()
        if not acc:
            QMessageBox.information(self, "Info", "Pilih akun terlebih dahulu.")
            return
        dlg = FormDialog(f"Ubah Akun — {acc.get('account_code')}", EDIT_FIELDS, initial=acc, parent=self)
        if dlg.exec():
            payload = dlg.result_payload()
            account_id = acc.get("id")
            if not account_id:
                QMessageBox.warning(self, "Gagal", "Akun ini tidak punya ID internal (data tidak lengkap dari server).")
                return
            run_task(
                api_client.put,
                on_success=lambda _r: self._after_write("Akun diperbarui."),
                on_error=self._on_write_error,
                path=f"{BASE}/accounts/{account_id}",
                json_body=payload,
            )

    def _create_account(self, parent_code: str | None = None) -> None:
        initial = {"parent_account_code": parent_code} if parent_code else None
        dlg = FormDialog("Akun Baru", CREATE_FIELDS, initial=initial, parent=self)
        if dlg.exec():
            payload = dlg.result_payload()
            run_task(
                api_client.post,
                on_success=lambda _r: self._after_write("Akun baru ditambahkan."),
                on_error=self._on_write_error,
                path=f"{BASE}/accounts",
                json_body=payload,
            )

    def _create_child_account(self) -> None:
        acc = self._selected_account()
        if not acc:
            QMessageBox.information(self, "Info", "Pilih akun induk terlebih dahulu.")
            return
        self._create_account(parent_code=acc.get("account_code"))

    def _delete_current(self) -> None:
        acc = self._selected_account()
        if not acc:
            QMessageBox.information(self, "Info", "Pilih akun terlebih dahulu.")
            return
        account_id = acc.get("id")
        if not account_id:
            QMessageBox.warning(self, "Gagal", "Akun ini tidak punya ID internal (data tidak lengkap dari server).")
            return
        confirm = QMessageBox.question(
            self, "Konfirmasi Hapus",
            f"Hapus/nonaktifkan akun {acc.get('account_code')} — {acc.get('account_name')}?\n\n"
            "Jika akun ini sudah pernah dipakai transaksi, backend biasanya akan menonaktifkannya "
            "(bukan menghapus permanen) demi menjaga integritas laporan historis.",
        )
        if confirm != QMessageBox.Yes:
            return
        run_task(
            api_client.delete,
            on_success=lambda _r: self._after_write("Akun dihapus/dinonaktifkan."),
            on_error=self._on_write_error,
            path=f"{BASE}/accounts/{account_id}",
        )

    def _after_write(self, message: str) -> None:
        self.status_label.setText(message)
        self.refresh()

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
