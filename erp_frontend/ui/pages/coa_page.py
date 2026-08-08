"""
ui/pages/coa_page.py
=====================
Bagan Akun (Chart of Accounts). Menampilkan struktur akun sebagai
QTreeWidget, dengan warna per tipe akun, ringkasan saldo per kategori,
tambah/ubah/nonaktifkan/kunci/duplikat akun, import/export, dan filter.

SINKRONISASI DENGAN BACKEND (lihat backend/adapters/primary_api/v1/
fastapi_coa_router.py dan backend/application/service_layer/service_coa.py):
    - Semua field di CREATE_FIELDS/EDIT_FIELDS PERSIS sama dengan
      AccountCreateSchema/AccountUpdateSchema di router.
    - Endpoint update/delete pakai `{account_id}` (UUID kolom `id`), BUKAN
      `account_code`.
    - `account_type` dikirim apa adanya (huruf kecil seperti "asset"); router
      punya validator yang menormalkan casing ke "Asset" dst, jadi frontend
      tidak perlu tahu detail casing backend.
"""
from __future__ import annotations

from typing import Any

from core.api_client import api_client
from core.formatting import extract_list, format_money
from core.workers import run_task
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
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

ACCOUNT_TYPES = ("asset", "liability", "equity", "revenue", "expense",
                  "contraasset", "contraliability", "contraequity")
STATUSES = ("active", "inactive", "suspended", "locked", "archived")
CASHFLOW_TYPES = ("", "operating", "investing", "financing")

# ----------------------------------------------------------------------
# Field untuk BUAT akun baru (semua field, termasuk yang tidak bisa diubah
# lagi setelah dibuat — account_code/account_type/normal_balance).
# ----------------------------------------------------------------------
CREATE_FIELDS = [
    FieldSpec("account_code", "Kode Akun", required=True,
              help_text="mis. 1101 (Asset diawali 1, Liability 2, Equity 3, Revenue 4, Expense 5/6)"),
    FieldSpec("account_name", "Nama Akun", required=True),
    FieldSpec("account_name_en", "Nama Akun (Inggris)"),
    FieldSpec("account_type", "Tipe Akun", FieldType.SELECT, choices=ACCOUNT_TYPES, required=True),
    FieldSpec("normal_balance", "Saldo Normal", FieldType.SELECT, choices=("debit", "credit"), required=True),
    FieldSpec("parent_account_code", "Kode Induk (opsional)"),
    FieldSpec("account_group", "Kategori / Grup", help_text="mis. Current Asset, Fixed Asset"),
    FieldSpec("is_header", "Header (tidak untuk posting)", FieldType.BOOL, default=False),
    FieldSpec("allow_posting", "Boleh Dipakai Posting Jurnal", FieldType.BOOL, default=True),
    FieldSpec("currency_code", "Mata Uang", default="IDR"),
    FieldSpec("opening_balance", "Saldo Awal", FieldType.DECIMAL, default=0),
    FieldSpec("sort_order", "Urutan Tampil", FieldType.NUMBER, default=0),
    FieldSpec("tax_code", "Kode Pajak"),
    FieldSpec("cashflow_type", "Klasifikasi Arus Kas", FieldType.SELECT, choices=CASHFLOW_TYPES),
    FieldSpec("budget_control", "Dikontrol Anggaran", FieldType.BOOL, default=False),
    FieldSpec("reconciliation_required", "Wajib Direkonsiliasi", FieldType.BOOL, default=False),
    FieldSpec("is_bank_account", "Akun Bank", FieldType.BOOL, default=False),
    FieldSpec("is_cash_account", "Akun Kas", FieldType.BOOL, default=False),
    FieldSpec("is_intercompany", "Akun Intercompany", FieldType.BOOL, default=False),
    FieldSpec("description", "Deskripsi", FieldType.TEXTAREA),
]

# ----------------------------------------------------------------------
# Field untuk UBAH akun (account_code/account_type/normal_balance TIDAK
# bisa diubah lagi setelah akun dibuat — sesuai AccountUpdateSchema
# backend; mengubah sifat dasar akun yang sudah dipakai transaksi akan
# merusak integritas laporan).
# ----------------------------------------------------------------------
EDIT_FIELDS = [
    FieldSpec("account_name", "Nama Akun", required=True),
    FieldSpec("account_name_en", "Nama Akun (Inggris)"),
    FieldSpec("status", "Status", FieldType.SELECT, choices=STATUSES),
    FieldSpec("parent_account_code", "Kode Induk (opsional)"),
    FieldSpec("account_group", "Kategori / Grup"),
    FieldSpec("allow_posting", "Boleh Dipakai Posting Jurnal", FieldType.BOOL, default=True),
    FieldSpec("sort_order", "Urutan Tampil", FieldType.NUMBER, default=0),
    FieldSpec("currency_code", "Mata Uang"),
    FieldSpec("tax_code", "Kode Pajak"),
    FieldSpec("cashflow_type", "Klasifikasi Arus Kas", FieldType.SELECT, choices=CASHFLOW_TYPES),
    FieldSpec("budget_control", "Dikontrol Anggaran", FieldType.BOOL, default=False),
    FieldSpec("reconciliation_required", "Wajib Direkonsiliasi", FieldType.BOOL, default=False),
    FieldSpec("is_bank_account", "Akun Bank", FieldType.BOOL, default=False),
    FieldSpec("is_cash_account", "Akun Kas", FieldType.BOOL, default=False),
    FieldSpec("is_intercompany", "Akun Intercompany", FieldType.BOOL, default=False),
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

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        header = QHBoxLayout()
        title = QLabel("🌳  Bagan Akun (Chart of Accounts)")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        header.addWidget(title)
        header.addStretch()

        self.type_filter = QComboBox()
        self.type_filter.addItem("Semua Tipe", "")
        for t in ACCOUNT_TYPES:
            self.type_filter.addItem(t.capitalize(), t)
        self.type_filter.setMaximumWidth(140)
        self.type_filter.currentIndexChanged.connect(lambda _i: self._apply_filter())
        header.addWidget(self.type_filter)

        self.status_filter = QComboBox()
        self.status_filter.addItem("Semua Status", "")
        for s in STATUSES:
            self.status_filter.addItem(s.capitalize(), s)
        self.status_filter.setMaximumWidth(130)
        self.status_filter.currentIndexChanged.connect(lambda _i: self._apply_filter())
        header.addWidget(self.status_filter)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Cari kode/nama akun...")
        self.search_edit.setMaximumWidth(220)
        self.search_edit.textChanged.connect(lambda _t: self._apply_filter())
        header.addWidget(self.search_edit)

        import_btn = QPushButton("⬆ Import")
        import_btn.clicked.connect(self._import_coa)
        header.addWidget(import_btn)

        export_btn = QPushButton("⬇ Export")
        export_btn.clicked.connect(self._export_coa)
        header.addWidget(export_btn)

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
        self.tree.setHeaderLabels([
            "Kode / Nama Akun", "Tipe", "Grup", "Saldo Normal", "Posting", "Status", "Saldo",
        ])
        self.tree.setColumnWidth(0, 300)
        self.tree.itemDoubleClicked.connect(self._on_edit_current)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
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

        duplicate_btn = QPushButton("⧉ Duplikat Akun")
        duplicate_btn.clicked.connect(self._duplicate_current)
        detail_layout.addWidget(duplicate_btn)

        toggle_row = QHBoxLayout()
        self.activate_btn = QPushButton("✓ Aktifkan")
        self.activate_btn.clicked.connect(self._activate_current)
        toggle_row.addWidget(self.activate_btn)
        self.deactivate_btn = QPushButton("⛔ Nonaktifkan")
        self.deactivate_btn.clicked.connect(self._deactivate_current)
        toggle_row.addWidget(self.deactivate_btn)
        detail_layout.addLayout(toggle_row)

        lock_row = QHBoxLayout()
        self.lock_btn = QPushButton("🔒 Kunci")
        self.lock_btn.clicked.connect(self._lock_current)
        lock_row.addWidget(self.lock_btn)
        self.unlock_btn = QPushButton("🔓 Buka Kunci")
        self.unlock_btn.clicked.connect(self._unlock_current)
        lock_row.addWidget(self.unlock_btn)
        detail_layout.addLayout(lock_row)

        delete_btn = QPushButton("🗑 Hapus / Arsipkan Akun")
        delete_btn.setProperty("class", "danger")
        delete_btn.clicked.connect(self._delete_current)
        detail_layout.addWidget(delete_btn)

        splitter.addWidget(detail_panel)
        splitter.setSizes([680, 280])
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)

        outer.addWidget(splitter, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    # ------------------------------------------------------------------
    # LOAD / RENDER
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self.status_label.setText("Memuat bagan akun...")
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{BASE}/accounts", params={"page_size": 5000, "include_inactive": True})

    def _on_loaded(self, payload: Any) -> None:
        self._accounts = extract_list(payload)
        self._apply_filter()
        self._render_summary(self._accounts)
        self.status_label.setText(f"{len(self._accounts)} akun dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _render_summary(self, accounts: list[dict[str, Any]]) -> None:
        totals: dict[str, float] = {}
        for acc in accounts:
            acc_type = str(acc.get("account_type", "")).lower()
            balance = acc.get("current_balance")
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

        accounts_sorted = sorted(
            accounts, key=lambda a: (a.get("sort_order") or 0, str(a.get("account_code", "")))
        )

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
        posting = "Ya" if acc.get("allow_posting") and not acc.get("is_header") else "Tidak"
        if acc.get("is_locked"):
            posting += " 🔒"
        balance = acc.get("current_balance")
        if balance in (None, 0):
            balance = acc.get("opening_balance") or 0
        item = QTreeWidgetItem([
            label,
            acc_type,
            str(acc.get("account_group", "") or ""),
            str(acc.get("normal_balance", "") or ""),
            posting,
            status,
            format_money(balance, acc.get("currency_code", "IDR")),
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

    def _apply_filter(self) -> None:
        text = self.search_edit.text().lower().strip()
        type_filter = self.type_filter.currentData() or ""
        status_filter = self.status_filter.currentData() or ""

        filtered = self._accounts
        if text:
            filtered = [
                a for a in filtered
                if text in str(a.get("account_code", "")).lower() or text in str(a.get("account_name", "")).lower()
            ]
        if type_filter:
            filtered = [a for a in filtered if str(a.get("account_type", "")).lower() == type_filter]
        if status_filter:
            filtered = [a for a in filtered if str(a.get("status", "")).lower() == status_filter]
        self._render_tree(filtered)

    # ------------------------------------------------------------------
    # SELECTION / DETAIL
    # ------------------------------------------------------------------
    def _on_selection_changed(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            self.detail_label.setText("Pilih akun untuk melihat detail.")
            return
        acc = items[0].data(0, Qt.UserRole) or {}
        lines = [f"<b>{acc.get('account_code')} — {acc.get('account_name')}</b>"]
        if acc.get("account_name_en"):
            lines.append(f"<i>{acc.get('account_name_en')}</i>")
        lines.append("")
        for key in ("account_type", "normal_balance", "status", "account_group",
                    "currency_code", "tax_code", "cashflow_type", "description"):
            if acc.get(key):
                lines.append(f"<b>{key.replace('_', ' ').title()}:</b> {acc.get(key)}")

        lines.append(f"<b>Saldo Berjalan:</b> {format_money(acc.get('current_balance') or 0, acc.get('currency_code', 'IDR'))}")
        lines.append(f"<b>Saldo Awal:</b> {format_money(acc.get('opening_balance') or 0, acc.get('currency_code', 'IDR'))}")
        lines.append(f"<b>Boleh Posting:</b> {'Ya' if acc.get('allow_posting') else 'Tidak'}")
        lines.append(f"<b>Sudah Dipakai Transaksi:</b> {'Ya' if acc.get('is_used_in_transaction') else 'Belum'}")
        if acc.get("is_locked"):
            lines.append(f"<b>🔒 Dikunci:</b> {acc.get('lock_reason') or '-'}")

        flags = [f for f in ("is_bank_account", "is_cash_account", "is_intercompany",
                              "budget_control", "reconciliation_required", "is_header") if acc.get(f)]
        if flags:
            lines.append(f"<b>Flag:</b> {', '.join(f.replace('is_', '').replace('_', ' ') for f in flags)}")
        self.detail_label.setText("<br>".join(lines))

    def _selected_account(self) -> dict[str, Any] | None:
        items = self.tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, Qt.UserRole) or {}

    def _on_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        self.tree.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction("✎ Ubah", self._on_edit_current)
        menu.addAction("+ Tambah Sub-Akun", self._create_child_account)
        menu.addAction("⧉ Duplikat", self._duplicate_current)
        menu.addSeparator()
        menu.addAction("✓ Aktifkan", self._activate_current)
        menu.addAction("⛔ Nonaktifkan", self._deactivate_current)
        menu.addAction("🔒 Kunci", self._lock_current)
        menu.addAction("🔓 Buka Kunci", self._unlock_current)
        menu.addSeparator()
        menu.addAction("🗑 Hapus / Arsipkan", self._delete_current)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # CREATE / UPDATE
    # ------------------------------------------------------------------
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

    def _duplicate_current(self) -> None:
        acc = self._selected_account()
        if not acc:
            QMessageBox.information(self, "Info", "Pilih akun terlebih dahulu.")
            return
        account_id = acc.get("id")
        if not account_id:
            return
        dlg = FormDialog(
            f"Duplikat Akun — {acc.get('account_code')}",
            [
                FieldSpec("new_account_code", "Kode Akun Baru", required=True),
                FieldSpec("new_account_name", "Nama Akun Baru (opsional)"),
            ],
            parent=self,
        )
        if dlg.exec():
            payload = dlg.result_payload()
            run_task(
                api_client.post,
                on_success=lambda _r: self._after_write("Akun berhasil diduplikat."),
                on_error=self._on_write_error,
                path=f"{BASE}/accounts/{account_id}/duplicate",
                json_body=payload,
            )

    # ------------------------------------------------------------------
    # STATUS ACTIONS
    # ------------------------------------------------------------------
    def _require_selection(self) -> dict[str, Any] | None:
        acc = self._selected_account()
        if not acc:
            QMessageBox.information(self, "Info", "Pilih akun terlebih dahulu.")
            return None
        if not acc.get("id"):
            QMessageBox.warning(self, "Gagal", "Akun ini tidak punya ID internal (data tidak lengkap dari server).")
            return None
        return acc

    def _activate_current(self) -> None:
        acc = self._require_selection()
        if not acc:
            return
        run_task(
            api_client.post,
            on_success=lambda _r: self._after_write(f"Akun {acc.get('account_code')} diaktifkan."),
            on_error=self._on_write_error,
            path=f"{BASE}/accounts/{acc.get('id')}/activate",
        )

    def _deactivate_current(self) -> None:
        acc = self._require_selection()
        if not acc:
            return
        run_task(
            api_client.delete,
            on_success=lambda _r: self._after_write(f"Akun {acc.get('account_code')} dinonaktifkan."),
            on_error=self._on_write_error,
            path=f"{BASE}/accounts/{acc.get('id')}",
        )

    def _lock_current(self) -> None:
        acc = self._require_selection()
        if not acc:
            return
        run_task(
            api_client.post,
            on_success=lambda _r: self._after_write(f"Akun {acc.get('account_code')} dikunci."),
            on_error=self._on_write_error,
            path=f"{BASE}/accounts/{acc.get('id')}/lock",
            params={"reason": "Dikunci manual dari aplikasi"},
        )

    def _unlock_current(self) -> None:
        acc = self._require_selection()
        if not acc:
            return
        run_task(
            api_client.post,
            on_success=lambda _r: self._after_write(f"Akun {acc.get('account_code')} dibuka kuncinya."),
            on_error=self._on_write_error,
            path=f"{BASE}/accounts/{acc.get('id')}/unlock",
        )

    def _delete_current(self) -> None:
        acc = self._require_selection()
        if not acc:
            return
        confirm = QMessageBox.question(
            self, "Konfirmasi Hapus",
            f"Hapus/arsipkan akun {acc.get('account_code')} — {acc.get('account_name')}?\n\n"
            "Jika akun ini sudah pernah dipakai transaksi atau masih punya sub-akun, backend "
            "otomatis akan mengarsipkannya (bukan menghapus permanen) demi menjaga integritas "
            "laporan historis.",
        )
        if confirm != QMessageBox.Yes:
            return
        run_task(
            api_client.delete,
            on_success=lambda _r: self._after_write("Akun dihapus/diarsipkan."),
            on_error=self._on_write_error,
            path=f"{BASE}/accounts/{acc.get('id')}",
            params={"permanent": True},
        )

    # ------------------------------------------------------------------
    # IMPORT / EXPORT
    # ------------------------------------------------------------------
    def _import_coa(self) -> None:
        file_path, _filter = QFileDialog.getOpenFileName(
            self, "Import Chart of Accounts", "", "COA Files (*.csv *.json);;All Files (*)"
        )
        if not file_path:
            return
        confirm = QMessageBox.question(
            self, "Konfirmasi Import",
            "Import akan menambah akun baru dan memperbarui akun yang sudah ada (mode: merge).\n"
            "Lanjutkan?",
        )
        if confirm != QMessageBox.Yes:
            return
        run_task(
            api_client.upload_file,
            on_success=self._on_import_done,
            on_error=self._on_write_error,
            path=f"{BASE}/import?mode=merge",
            file_path=file_path,
        )

    def _on_import_done(self, result: Any) -> None:
        result = result or {}
        msg = result.get("message", "Import selesai.")
        errors = result.get("errors") or []
        if errors:
            msg += f"\n\n{len(errors)} baris bermasalah:\n" + "\n".join(str(e) for e in errors[:10])
        QMessageBox.information(self, "Import COA", msg)
        self.refresh()

    def _export_coa(self) -> None:
        file_path, _filter = QFileDialog.getSaveFileName(
            self, "Export Chart of Accounts", "coa_export.csv", "CSV Files (*.csv);;JSON Files (*.json)"
        )
        if not file_path:
            return
        fmt = "json" if file_path.lower().endswith(".json") else "csv"
        run_task(
            api_client.download_file,
            on_success=lambda _r: self.status_label.setText(f"Export disimpan ke {file_path}"),
            on_error=self._on_write_error,
            path=f"{BASE}/export",
            save_path=file_path,
            params={"format": fmt, "include_inactive": True},
        )

    # ------------------------------------------------------------------
    def _after_write(self, message: str) -> None:
        self.status_label.setText(message)
        self.refresh()

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
