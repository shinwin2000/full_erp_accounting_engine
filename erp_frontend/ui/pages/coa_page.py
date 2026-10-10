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

PANEL DETAIL AKUN
    - Field detail dirender sebagai QGridLayout (bukan <table> di QLabel),
      supaya teks otomatis wrap dan tidak perlu scroll horizontal.

BARIS AKSI
    - Padding tombol 2px 6px, font 12px, spacing 4, separator rapat, dan
      label terpanjang diperpendek ("+ Sub", "🗑 Hapus") agar seluruh tombol
      (termasuk Export & Refresh) muat di layar 1440px tanpa terpotong.
"""
from __future__ import annotations

from typing import Any

from core.api_client import api_client
from core.formatting import extract_list, format_datetime, format_money
from core.workers import run_task
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QGridLayout,
    QHeaderView,
    QInputDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from registry.module_registry import FieldSpec, FieldType
from ui.widgets.form_dialog import FormDialog
from ui.widgets.modern_form_dialog import ModernFormDialog
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
              help_text="mis. 1101 (Asset diawali 1, Liability 2, Equity 3, Revenue 4, Expense 5/6)", section="Identitas Akun"),
    FieldSpec("account_name", "Nama Akun", required=True, section="Identitas Akun"),
    FieldSpec("account_name_en", "Nama Akun (Inggris)", section="Identitas Akun"),
    FieldSpec("account_type", "Tipe Akun", FieldType.SELECT, choices=ACCOUNT_TYPES, required=True, section="Identitas Akun"),
    FieldSpec("normal_balance", "Saldo Normal", FieldType.SELECT, choices=("debit", "credit"), required=True, section="Identitas Akun"),
    FieldSpec("parent_account_code", "Kode Induk (opsional)", section="Hierarki & Klasifikasi"),
    FieldSpec("account_group", "Kategori / Grup", help_text="mis. Current Asset, Fixed Asset", section="Hierarki & Klasifikasi"),
    FieldSpec("is_header", "Header (tidak untuk posting)", FieldType.BOOL, default=False, section="Hierarki & Klasifikasi"),
    FieldSpec("allow_posting", "Boleh Dipakai Posting Jurnal", FieldType.BOOL, default=True, section="Posting & Keuangan"),
    FieldSpec("currency_code", "Mata Uang", default="IDR", section="Posting & Keuangan"),
    FieldSpec("opening_balance", "Saldo Awal", FieldType.DECIMAL, default=0, section="Posting & Keuangan"),
    FieldSpec("sort_order", "Urutan Tampil", FieldType.NUMBER, default=0, section="Hierarki & Klasifikasi"),
    FieldSpec("tax_code", "Kode Pajak", section="Posting & Keuangan"),
    FieldSpec("cashflow_type", "Klasifikasi Arus Kas", FieldType.SELECT, choices=CASHFLOW_TYPES, section="Posting & Keuangan"),
    FieldSpec("budget_control", "Dikontrol Anggaran", FieldType.BOOL, default=False, section="Kontrol & Penanda"),
    FieldSpec("reconciliation_required", "Wajib Direkonsiliasi", FieldType.BOOL, default=False, section="Kontrol & Penanda"),
    FieldSpec("is_bank_account", "Akun Bank", FieldType.BOOL, default=False, section="Kontrol & Penanda"),
    FieldSpec("is_cash_account", "Akun Kas", FieldType.BOOL, default=False, section="Kontrol & Penanda"),
    FieldSpec("is_intercompany", "Akun Intercompany", FieldType.BOOL, default=False, section="Kontrol & Penanda"),
    FieldSpec("description", "Deskripsi", FieldType.TEXTAREA, section="Keterangan"),
]

# ----------------------------------------------------------------------
# Field untuk UBAH akun (account_code/account_type/normal_balance TIDAK
# bisa diubah lagi setelah akun dibuat — sesuai AccountUpdateSchema
# backend; mengubah sifat dasar akun yang sudah dipakai transaksi akan
# merusak integritas laporan).
# ----------------------------------------------------------------------
EDIT_FIELDS = [
    FieldSpec("account_name", "Nama Akun", required=True, section="Identitas Akun"),
    FieldSpec("account_name_en", "Nama Akun (Inggris)", section="Identitas Akun"),
    FieldSpec("status", "Status", FieldType.SELECT, choices=STATUSES, section="Identitas Akun"),
    FieldSpec("parent_account_code", "Kode Induk (opsional)", section="Hierarki & Klasifikasi"),
    FieldSpec("account_group", "Kategori / Grup", section="Hierarki & Klasifikasi"),
    FieldSpec("allow_posting", "Boleh Dipakai Posting Jurnal", FieldType.BOOL, default=True, section="Posting & Keuangan"),
    FieldSpec("sort_order", "Urutan Tampil", FieldType.NUMBER, default=0, section="Hierarki & Klasifikasi"),
    FieldSpec("currency_code", "Mata Uang", section="Posting & Keuangan"),
    FieldSpec("tax_code", "Kode Pajak", section="Posting & Keuangan"),
    FieldSpec("cashflow_type", "Klasifikasi Arus Kas", FieldType.SELECT, choices=CASHFLOW_TYPES, section="Posting & Keuangan"),
    FieldSpec("budget_control", "Dikontrol Anggaran", FieldType.BOOL, default=False, section="Kontrol & Penanda"),
    FieldSpec("reconciliation_required", "Wajib Direkonsiliasi", FieldType.BOOL, default=False, section="Kontrol & Penanda"),
    FieldSpec("is_bank_account", "Akun Bank", FieldType.BOOL, default=False, section="Kontrol & Penanda"),
    FieldSpec("is_cash_account", "Akun Kas", FieldType.BOOL, default=False, section="Kontrol & Penanda"),
    FieldSpec("is_intercompany", "Akun Intercompany", FieldType.BOOL, default=False, section="Kontrol & Penanda"),
    FieldSpec("description", "Deskripsi", FieldType.TEXTAREA, section="Keterangan"),
]

TYPE_COLORS = {
    "asset": "#2563EB",
    "liability": "#DC2626",
    "equity": "#7C3AED",
    "revenue": "#059669",
    "expense": "#D97706",
}


class _CoaRowDelegate(QStyledItemDelegate):
    """Baris terpilih: latar ungu + teks putih. Tanpa ini teks berwarna per
    tipe akun (biru/merah/hijau) menjadi tidak terbaca di atas warna sorot."""

    def initStyleOption(self, option, index):  # noqa: N802
        super().initStyleOption(option, index)
        if option.state & QStyle.State_Selected:
            option.palette.setColor(QPalette.HighlightedText, QColor("white"))
            option.palette.setColor(QPalette.Highlight, QColor("#7C3AED"))
            option.palette.setColor(QPalette.Text, QColor("white"))
            option.backgroundBrush = QColor("#7C3AED")
            option.font.setBold(True)


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
        outer.setSpacing(10)

        # ---------- Baris 1: judul + filter + import/export/refresh/baru ----------
        header = QHBoxLayout()
        title = QLabel("🌳  Bagan Akun (COA)")
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
        self.search_edit.setMaximumWidth(200)
        self.search_edit.setMinimumWidth(110)
        self.search_edit.textChanged.connect(lambda _t: self._apply_filter())
        header.addWidget(self.search_edit)

        new_btn = QPushButton("+ Akun Baru")
        new_btn.setObjectName("primaryButton")
        new_btn.clicked.connect(lambda: self._create_account(parent_code=None))
        header.addWidget(new_btn)
        outer.addLayout(header)

        # ---------- Ringkasan saldo per tipe akun ----------
        self.summary_row = QHBoxLayout()
        self.summary_row.setSpacing(12)
        self.summary_cards: dict[str, KpiCard] = {}
        for acc_type, label in [
            ("asset", "Total Aset"), ("liability", "Total Kewajiban"),
            ("equity", "Total Ekuitas"), ("revenue", "Total Pendapatan"), ("expense", "Total Beban"),
        ]:
            card = KpiCard(label, color=TYPE_COLORS[acc_type])
            card.setMinimumHeight(84)
            self.summary_cards[acc_type] = card
            self.summary_row.addWidget(card)
        outer.addLayout(self.summary_row)

        # ---------- Baris aksi (di ATAS tabel) ----------
        # Padding 2px 6px, font 12px, spacing 4, separator rapat, label
        # terpanjang diperpendek -- supaya seluruh tombol termasuk Refresh
        # muat di layar 1440px tanpa terpotong.
        actions = QFrame()
        actions.setObjectName("coaActionBar")
        actions.setStyleSheet(
            "QFrame#coaActionBar { background:white; border:1px solid #E9D5FF; border-radius:12px; }"
            "QFrame#coaActionBar QPushButton { padding:2px 6px; font-size:12px; }"
            "QFrame#coaActionBar QLabel#sep { color:#D8B4FE; padding:0 1px; }"
        )
        act = QHBoxLayout(actions)
        act.setContentsMargins(10, 6, 10, 6)
        act.setSpacing(4)

        def _btn(text: str, slot, tip: str = "", danger: bool = False) -> QPushButton:
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            if danger:
                b.setProperty("class", "danger")
            b.clicked.connect(slot)
            act.addWidget(b)
            return b

        def _sep() -> None:
            sp = QLabel("│")
            sp.setObjectName("sep")
            act.addWidget(sp)

        self.add_child_btn = _btn("+ Sub", self._create_child_account, "Tambah sub-akun di bawah akun terpilih")
        self.edit_btn = _btn("✎ Ubah", self._on_edit_current, "Ubah akun terpilih (atau klik dua kali barisnya)")
        self.duplicate_btn = _btn("⧉ Duplikat", self._duplicate_current, "Salin akun terpilih ke kode baru")
        _sep()
        self.activate_btn = _btn("✓ Aktifkan", self._activate_current)
        self.deactivate_btn = _btn("⛔ Nonaktifkan", self._deactivate_current)
        _sep()
        self.lock_btn = _btn("🔒 Kunci", self._lock_current, "Kunci akun agar tidak bisa dipakai/diubah")
        self.unlock_btn = _btn("🔓 Buka Kunci", self._unlock_current)
        _sep()
        self.delete_btn = _btn("🗑 Hapus", self._delete_current,
                               "Hapus permanen bila belum dipakai, kalau sudah dipakai otomatis diarsipkan", danger=True)
        self.history_btn = _btn("📜 Riwayat", self._show_history, "Lihat jejak perubahan akun terpilih (siapa, kapan, apa)")
        self.approvals_btn = _btn("✅ Persetujuan", self._show_approvals,
                                  "Permintaan hapus/buka kunci akun yang menunggu persetujuan (maker-checker)")
        _sep()
        self.import_btn = _btn("⬆ Import", self._import_coa)
        self.export_btn = _btn("⬇ Export", self._export_coa)
        self.refresh_btn = _btn("⟳ Refresh", self.refresh)
        act.addStretch()

        # Baris aksi dibungkus scroll horizontal: kalau layar sangat sempit,
        # tombol bisa digeser -- jendela utama TIDAK dipaksa melebar.
        actions.adjustSize()
        bar_scroll = QScrollArea()
        bar_scroll.setWidgetResizable(True)
        bar_scroll.setFrameShape(QFrame.NoFrame)
        bar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        bar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        bar_scroll.setWidget(actions)
        bar_scroll.setFixedHeight(actions.sizeHint().height() + 10)
        bar_scroll.setStyleSheet("QScrollArea { background:transparent; }")
        outer.addWidget(bar_scroll)
        self.selection_label = QLabel("")
        self.selection_label.setStyleSheet("color:#6B7280; font-size:12px;")
        outer.addWidget(self.selection_label)

        # ---------- Tabel akun (lebar penuh) + panel detail di bawah ----------
        splitter = QSplitter(Qt.Vertical)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([
            "Kode / Nama Akun", "Tipe", "Grup", "Saldo Normal", "Posting", "Status", "Saldo",
        ])
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setUniformRowHeights(True)
        self.tree.setItemDelegate(_CoaRowDelegate(self.tree))
        self.tree.setStyleSheet(
            "QTreeWidget::item { padding:5px 2px; }"
            "QTreeWidget::item:hover { background:#EDE9FE; }"
            "QTreeWidget::item:selected { background:#7C3AED; color:white; }"
            "QTreeWidget::item:selected:hover { background:#6D28D9; color:white; }"
        )
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in ((1, 95), (2, 110), (3, 105), (4, 70), (5, 70), (6, 140)):
            hdr.setSectionResizeMode(col, QHeaderView.Interactive)
            self.tree.setColumnWidth(col, width)
        self.tree.itemDoubleClicked.connect(self._on_edit_current)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        splitter.addWidget(self.tree)

        # ---------- Panel Detail Akun (grid, tanpa scroll horizontal) ----------
        detail_card = QFrame()
        detail_card.setObjectName("coaDetail")
        detail_card.setStyleSheet(
            "QFrame#coaDetail { background:white; border:1px solid #E9D5FF; border-radius:12px; }"
        )
        detail_layout = QVBoxLayout(detail_card)
        detail_layout.setContentsMargins(16, 10, 16, 10)
        detail_layout.setSpacing(6)

        detail_title = QLabel("Detail Akun")
        detail_title.setStyleSheet("font-weight:700; font-size:14px; border:none;")
        detail_layout.addWidget(detail_title)

        # Baris 1: kode + nama akun (header).
        self.detail_head = QLabel("Pilih akun untuk melihat detail.")
        self.detail_head.setTextFormat(Qt.RichText)
        self.detail_head.setWordWrap(True)
        self.detail_head.setStyleSheet("border:none;")
        detail_layout.addWidget(self.detail_head)

        # Baris 2: grid field (label:value), 4 pasang per baris.
        # Pengganti <table> di QLabel yang menyebabkan scroll horizontal.
        self.detail_grid_host = QWidget()
        self.detail_grid_host.setStyleSheet("background:transparent;")
        self.detail_grid = QGridLayout(self.detail_grid_host)
        self.detail_grid.setContentsMargins(0, 0, 0, 0)
        self.detail_grid.setHorizontalSpacing(18)
        self.detail_grid.setVerticalSpacing(4)
        detail_layout.addWidget(self.detail_grid_host)

        # Baris 3: keterangan tambahan (dikunci, penanda, deskripsi).
        self.detail_footer = QLabel("")
        self.detail_footer.setTextFormat(Qt.RichText)
        self.detail_footer.setWordWrap(True)
        self.detail_footer.setStyleSheet("border:none; color:#374151;")
        detail_layout.addWidget(self.detail_footer)

        detail_layout.addStretch(1)
        splitter.addWidget(detail_card)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([520, 190])
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)

        outer.addWidget(splitter, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)
        self._update_action_buttons()

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
        # BUGFIX: (1) akun header tidak dijumlahkan lagi (saldo anaknya sudah
        # terhitung -> sebelumnya bisa dobel), (2) akun kontra (mis.
        # Akumulasi Penyusutan = contraasset) MENGURANGI total tipe induknya,
        # bukan dijumlahkan / diabaikan, (3) hanya akun aktif yang dihitung.
        totals: dict[str, float] = {}
        for acc in accounts:
            if acc.get("is_header") or str(acc.get("status", "")).lower() in ("archived", "inactive"):
                continue
            acc_type = str(acc.get("account_type", "")).lower()
            sign = 1.0
            if acc_type.startswith("contra"):
                acc_type = acc_type[len("contra"):]
                sign = -1.0
            balance = acc.get("current_balance")
            if balance is None:
                balance = acc.get("opening_balance") or 0
            try:
                totals[acc_type] = totals.get(acc_type, 0.0) + sign * float(balance)
            except (TypeError, ValueError):
                pass
        for acc_type, card in self.summary_cards.items():
            card.set_value(format_money(totals.get(acc_type, 0)))

    def _render_tree(self, accounts: list[dict[str, Any]]) -> None:
        selected_code = None
        cur = self._selected_account()
        if cur:
            selected_code = cur.get("account_code")

        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        accounts_sorted = sorted(
            accounts, key=lambda a: (a.get("sort_order") or 0, str(a.get("account_code", "")))
        )
        # Dua tahap: buat SEMUA item dulu, baru pasang induk-anak. Cara lama
        # (satu lintasan) membuat akun anak yang urutannya lebih dulu dari
        # induknya bisa terpasang salah.
        by_code: dict[str, QTreeWidgetItem] = {}
        for acc in accounts_sorted:
            by_code[str(acc.get("account_code", ""))] = self._make_item(acc)

        def _has_cycle(code: str) -> bool:
            seen = set()
            while code and code not in seen:
                seen.add(code)
                item = by_code.get(code)
                if item is None:
                    return False
                code = str((item.data(0, Qt.UserRole) or {}).get("parent_account_code") or "")
            return bool(code)

        for acc in accounts_sorted:
            code = str(acc.get("account_code", ""))
            item = by_code[code]
            parent_code = str(acc.get("parent_account_code") or "")
            if parent_code and parent_code != code and parent_code in by_code and not _has_cycle(parent_code):
                by_code[parent_code].addChild(item)
            else:
                self.tree.addTopLevelItem(item)

        # Saldo akun header = jumlah saldo anak-anaknya (kalau header tidak
        # punya saldo sendiri), supaya induk grup tidak tampil Rp 0.
        def _rollup(item: QTreeWidgetItem) -> float:
            acc = item.data(0, Qt.UserRole) or {}
            own = float(acc.get("current_balance") or 0)
            total = 0.0
            for i in range(item.childCount()):
                child = item.child(i)
                child_val = _rollup(child)
                child_type = str((child.data(0, Qt.UserRole) or {}).get("account_type", "")).lower()
                own_type = str(acc.get("account_type", "")).lower()
                # akun kontra mengurangi induknya (mis. Akumulasi Penyusutan)
                if child_type.startswith("contra") and not own_type.startswith("contra"):
                    child_val = -child_val
                total += child_val
            if item.childCount():
                if acc.get("is_header") or not acc.get("allow_posting"):
                    own = total
                    item.setText(6, format_money(own, acc.get("currency_code", "IDR")))
                    f = item.font(0)
                    f.setBold(True)
                    for col in range(item.columnCount()):
                        item.setFont(col, f)
                return own
            return own

        for i in range(self.tree.topLevelItemCount()):
            _rollup(self.tree.topLevelItem(i))

        self.tree.expandAll()
        if selected_code and str(selected_code) in by_code:
            self.tree.setCurrentItem(by_code[str(selected_code)])
        self.tree.setUpdatesEnabled(True)
        self._update_action_buttons()

    def _make_item(self, acc: dict[str, Any]) -> QTreeWidgetItem:
        label = f"{acc.get('account_code', '')} — {acc.get('account_name', '')}"
        acc_type = str(acc.get("account_type", "") or "")
        status = str(acc.get("status", "") or "")
        posting = "Ya" if acc.get("allow_posting") and not acc.get("is_header") else "Tidak"
        if acc.get("is_locked"):
            posting += " 🔒"
        balance = acc.get("current_balance")
        if balance is None:
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
        item.setTextAlignment(6, Qt.AlignRight | Qt.AlignVCenter)
        color = TYPE_COLORS.get(acc_type.lower().replace("contra", ""))
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
        self._update_action_buttons()

        # Bersihkan grid dari render sebelumnya.
        while self.detail_grid.count():
            item = self.detail_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        items = self.tree.selectedItems()
        if not items:
            self.detail_head.setText("Pilih akun untuk melihat detail.")
            self.detail_footer.setText("")
            return

        acc = items[0].data(0, Qt.UserRole) or {}
        cur = acc.get("currency_code", "IDR")

        # Header: kode — nama (+ nama Inggris kalau ada).
        head = f"<span style='font-size:14px'><b>{acc.get('account_code')} — {acc.get('account_name')}</b></span>"
        if acc.get("account_name_en"):
            head += f" &nbsp;<i style='color:#6B7280'>{acc.get('account_name_en')}</i>"
        self.detail_head.setText(head)

        # Field: 4 pasang (label, value) per baris.
        rows = [
            ("Tipe", acc.get("account_type")),
            ("Saldo Normal", acc.get("normal_balance")),
            ("Status", acc.get("status")),
            ("Grup", acc.get("account_group")),
            ("Induk", acc.get("parent_account_code")),
            ("Mata Uang", acc.get("currency_code")),
            ("Kode Pajak", acc.get("tax_code")),
            ("Arus Kas", acc.get("cashflow_type")),
            ("Saldo Berjalan", format_money(acc.get("current_balance") or 0, cur)),
            ("Saldo Awal", format_money(acc.get("opening_balance") or 0, cur)),
            ("Boleh Posting", "Ya" if acc.get("allow_posting") and not acc.get("is_header") else "Tidak"),
            ("Dipakai Transaksi", "Ya" if acc.get("is_used_in_transaction") else "Belum"),
        ]
        rows = [(k, v) for k, v in rows if v not in (None, "")]
        cols = 4
        for i, (k, v) in enumerate(rows):
            r, c = divmod(i, cols)
            lbl = QLabel(f"{k}:")
            lbl.setStyleSheet("color:#6B7280; border:none;")
            val = QLabel(str(v))
            val.setStyleSheet("border:none; font-weight:600;")
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.detail_grid.addWidget(lbl, r, c * 2)
            self.detail_grid.addWidget(val, r, c * 2 + 1)
        # Kolom terakhir melebar agar layout tidak "menyempit" saat sempit.
        self.detail_grid.setColumnStretch(cols * 2, 1)

        # Footer: kunci, penanda, deskripsi.
        footer_parts: list[str] = []
        if acc.get("is_locked"):
            footer_parts.append(f"<b>🔒 Dikunci:</b> {acc.get('lock_reason') or '-'}")
        flags = [
            f for f in (
                "is_bank_account", "is_cash_account", "is_intercompany",
                "budget_control", "reconciliation_required", "is_header",
            ) if acc.get(f)
        ]
        if flags:
            footer_parts.append(
                "<b>Penanda:</b> "
                + ", ".join(f.replace("is_", "").replace("_", " ") for f in flags)
            )
        if acc.get("description"):
            footer_parts.append(f"<span style='color:#6B7280'>{acc.get('description')}</span>")
        self.detail_footer.setText("<br>".join(footer_parts))

    def _update_action_buttons(self) -> None:
        """Aktif/nonaktifkan tombol sesuai akun yang dipilih & statusnya."""
        acc = self._selected_account() if hasattr(self, "tree") else None
        has = bool(acc)
        status = str((acc or {}).get("status", "")).lower()
        locked = bool((acc or {}).get("is_locked"))
        for b in (self.add_child_btn, self.edit_btn, self.duplicate_btn, self.delete_btn, self.history_btn):
            b.setEnabled(has)
        self.activate_btn.setEnabled(has and status != "active")
        self.deactivate_btn.setEnabled(has and status == "active")
        self.lock_btn.setEnabled(has and not locked)
        self.unlock_btn.setEnabled(has and locked)
        self.selection_label.setText(
            f"Terpilih: {acc.get('account_code')} — {acc.get('account_name')}" if has
            else "Pilih akun di tabel untuk memakai tombol di samping."
        )

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
        menu.addAction("📜 Riwayat", self._show_history)
        menu.addAction("🗑 Hapus / Arsipkan", self._delete_current)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # CREATE / UPDATE
    # ------------------------------------------------------------------
    def _parent_choices(self, exclude_code: str | None = None) -> tuple[str, ...]:
        """Kode akun yang boleh jadi induk: backend menolak induk yang
        allow_posting=True, jadi hanya akun header/non-posting yang ditawarkan."""
        codes = sorted(
            str(a.get("account_code"))
            for a in self._accounts
            if (a.get("is_header") or not a.get("allow_posting"))
            and str(a.get("status", "")).lower() == "active"
            and str(a.get("account_code")) != str(exclude_code or "")
        )
        return ("", *codes)

    def _with_parent_choices(self, fields: list[FieldSpec], exclude_code: str | None = None) -> list[FieldSpec]:
        out = []
        for f in fields:
            if f.name == "parent_account_code":
                f = FieldSpec(
                    f.name, f.label, FieldType.SELECT, choices=self._parent_choices(exclude_code),
                    section=f.section,
                    help_text="Pilih akun header sebagai induk (kosongkan = akun tingkat atas)",
                )
            out.append(f)
        return out

    def _on_edit_current(self, *_args) -> None:
        acc = self._selected_account()
        if not acc:
            QMessageBox.information(self, "Info", "Pilih akun terlebih dahulu.")
            return
        account_id = acc.get("id")
        if not account_id:
            QMessageBox.warning(self, "Gagal", "Akun ini tidak punya ID internal (data tidak lengkap dari server).")
            return
        if acc.get("is_locked"):
            QMessageBox.information(self, "Akun Dikunci",
                                    f"Akun {acc.get('account_code')} sedang dikunci. Buka kunci dulu untuk mengubahnya.")
            return
        initial = dict(acc)
        # Nilai status dari server kadang huruf besar; samakan dgn pilihan form.
        initial["status"] = str(initial.get("status") or "").lower()
        fields = self._with_parent_choices(EDIT_FIELDS, exclude_code=acc.get("account_code"))
        dlg = ModernFormDialog(
            f"Ubah Akun — {acc.get('account_code')}", fields, initial=initial, parent=self,
            icon="✏️", columns=2, send_empty_as_null=True,
            subtitle=f"{acc.get('account_code')} • {acc.get('account_name')}  |  "
                     "Kode, tipe, dan saldo normal tidak dapat diubah setelah akun dibuat.",
        )
        if dlg.exec():
            payload = self._normalize_payload(dlg.result_payload())
            # Mengosongkan dropdown induk = jadikan akun tingkat atas. Backend
            # menganggap None sebagai "tidak diubah" dan "" sebagai "lepas induk",
            # jadi harus dikirim "" -- kalau tidak, induk tidak pernah bisa dilepas.
            if acc.get("parent_account_code") and not payload.get("parent_account_code"):
                payload["parent_account_code"] = ""
            run_task(
                api_client.put,
                on_success=lambda _r: self._after_write("Akun diperbarui."),
                on_error=self._on_write_error,
                path=f"{BASE}/accounts/{account_id}",
                json_body=payload,
            )

    @staticmethod
    def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
        """Akun header tidak boleh dipakai posting (aturan backend & trigger DB)."""
        if payload.get("is_header"):
            payload["allow_posting"] = False
        return payload

    def _create_account(self, parent_code: str | None = None) -> None:
        initial: dict[str, Any] = {}
        subtitle = "Isi data akun baru. Kode akun mengikuti tipe (Aset 1, Kewajiban 2, Ekuitas 3, Pendapatan 4, Beban 5/6)."
        if parent_code:
            initial["parent_account_code"] = parent_code
            parent = next((a for a in self._accounts if a.get("account_code") == parent_code), None)
            if parent:
                # Sub-akun mewarisi tipe, saldo normal, grup & mata uang induknya.
                for k in ("account_type", "normal_balance", "account_group", "currency_code"):
                    if parent.get(k):
                        initial[k] = str(parent[k]).lower() if k in ("account_type", "normal_balance") else parent[k]
                subtitle = f"Sub-akun dari {parent_code} — {parent.get('account_name')}."
        fields = self._with_parent_choices(CREATE_FIELDS)
        dlg = ModernFormDialog(
            "Tambah Akun Baru", fields, initial=initial or None, parent=self,
            icon="🌳", columns=2, subtitle=subtitle,
        )
        # Saldo normal otomatis mengikuti tipe akun (bisa diubah manual).
        type_w = dlg._inputs.get("account_type")
        bal_w = dlg._inputs.get("normal_balance")
        if type_w is not None and bal_w is not None:
            def _sync(text: str) -> None:
                debit = text.strip().lower() in ("asset", "expense", "contraliability", "contraequity")
                bal_w.setCurrentText("debit" if debit else "credit")
            type_w.currentTextChanged.connect(_sync)
            if not initial.get("normal_balance"):
                _sync(type_w.currentText())
        if dlg.exec():
            payload = self._normalize_payload(dlg.result_payload())
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
        dlg = ModernFormDialog(
            f"Duplikat Akun — {acc.get('account_code')}",
            [
                FieldSpec("new_account_code", "Kode Akun Baru", required=True, section="Akun Salinan"),
                FieldSpec("new_account_name", "Nama Akun Baru (opsional)", section="Akun Salinan"),
            ],
            parent=self, icon="⧉", columns=1,
            subtitle=f"Menyalin pengaturan dari {acc.get('account_code')} — {acc.get('account_name')}.",
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
    # RIWAYAT / AUDIT TRAIL
    # ------------------------------------------------------------------
    def _show_history(self) -> None:
        acc = self._require_selection()
        if not acc:
            return
        self.status_label.setText("Memuat riwayat perubahan...")
        run_task(
            api_client.get,
            on_success=lambda rows: self._render_history(acc, rows),
            on_error=self._on_write_error,
            path=f"{BASE}/accounts/{acc.get('id')}/history",
        )

    def _render_history(self, acc: dict[str, Any], rows: Any) -> None:
        self.status_label.setText("")
        rows = rows if isinstance(rows, list) else []
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Riwayat Akun — {acc.get('account_code')} {acc.get('account_name')}")
        dlg.resize(900, 460)
        lay = QVBoxLayout(dlg)
        table = QTableWidget(len(rows), 6)
        table.setHorizontalHeaderLabels(["Waktu", "Aksi", "Field", "Nilai Lama", "Nilai Baru", "Alasan"])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        for r, h in enumerate(rows):
            vals = [
                format_datetime(h.get("timestamp")), h.get("action"), h.get("field"),
                h.get("old_value"), h.get("new_value"), h.get("reason"),
            ]
            for c, v in enumerate(vals):
                table.setItem(r, c, QTableWidgetItem("-" if v in (None, "") else str(v)))
        table.resizeColumnsToContents()
        lay.addWidget(table)
        if not rows:
            lay.addWidget(QLabel("Belum ada riwayat tercatat untuk akun ini."))
        close = QPushButton("Tutup")
        close.clicked.connect(dlg.accept)
        lay.addWidget(close)
        dlg.exec()

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
        reason, ok = QInputDialog.getText(
            self, "Kunci Akun", f"Alasan mengunci akun {acc.get('account_code')}:",
            text="Dikunci manual dari aplikasi",
        )
        if not ok or not reason.strip():
            return
        run_task(
            api_client.post,
            on_success=lambda _r: self._after_write(f"Akun {acc.get('account_code')} dikunci."),
            on_error=self._on_write_error,
            path=f"{BASE}/accounts/{acc.get('id')}/lock",
            params={"reason": reason.strip()},
        )

    def _unlock_current(self) -> None:
        acc = self._require_selection()
        if not acc:
            return
        run_task(
            api_client.post,
            on_success=lambda r: self._after_write(
                r.get("message") if isinstance(r, dict) and r.get("message")
                else f"Akun {acc.get('account_code')} dibuka kuncinya."
            ),
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
            "Permintaan ini akan diajukan dan baru dijalankan setelah DISETUJUI pengguna lain "
            "(menu ✅ Persetujuan). Jika akun sudah dipakai transaksi atau punya sub-akun, "
            "saat disetujui akun diarsipkan (bukan dihapus permanen) demi integritas laporan.",
        )
        if confirm != QMessageBox.Yes:
            return
        reason, ok = QInputDialog.getText(
            self, "Alasan", f"Alasan menghapus/mengarsipkan akun {acc.get('account_code')}:"
        )
        if not ok or not reason.strip():
            QMessageBox.information(self, "Dibatalkan", "Alasan wajib diisi.")
            return
        run_task(
            api_client.delete,
            on_success=lambda r: self._after_write(
                (r or {}).get("message") or "Akun dihapus/diarsipkan." if isinstance(r, dict) else "Akun dihapus/diarsipkan."
            ),
            on_error=self._on_write_error,
            path=f"{BASE}/accounts/{acc.get('id')}",
            params={"permanent": True, "reason": reason.strip()},
        )

    # ------------------------------------------------------------------
    # IMPORT / EXPORT
    # ------------------------------------------------------------------
    def _import_coa(self) -> None:
        file_path, _filter = QFileDialog.getOpenFileName(
            self, "Import Chart of Accounts", "",
            "File COA (*.xlsx *.csv *.json);;Excel (*.xlsx);;CSV (*.csv);;JSON (*.json)",
        )
        if not file_path:
            return
        self._import_path = file_path
        # Langkah 1: validasi dulu (dry-run, tidak menyimpan apa pun).
        run_task(
            api_client.upload_file,
            on_success=self._on_import_validated,
            on_error=self._on_write_error,
            path=f"{BASE}/import?mode=merge&validate_only=true",
            file_path=file_path,
        )

    def _on_import_validated(self, result: Any) -> None:
        result = result or {}
        errors = result.get("errors") or []
        msg = result.get("message", "Validasi selesai.")
        if errors:
            msg += f"\n\n{len(errors)} baris bermasalah (akan dilewati):\n" + "\n".join(
                str(e) for e in errors[:10]
            )
        msg += "\n\nLanjutkan import (mode merge: tambah akun baru, akun lama tidak diubah)?"
        if QMessageBox.question(self, "Hasil Validasi Import", msg) != QMessageBox.Yes:
            return
        run_task(
            api_client.upload_file,
            on_success=self._on_import_done,
            on_error=self._on_write_error,
            path=f"{BASE}/import?mode=merge",
            file_path=self._import_path,
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
        xlsx_f, csv_f, json_f = "Excel (*.xlsx)", "CSV (*.csv)", "JSON (*.json)"
        file_path, chosen = QFileDialog.getSaveFileName(
            self, "Export Chart of Accounts", "coa_export.xlsx", f"{xlsx_f};;{csv_f};;{json_f}"
        )
        if not file_path:
            return
        low = file_path.lower()
        if low.endswith(".xlsx"):
            fmt = "excel"
        elif low.endswith(".csv"):
            fmt = "csv"
        elif low.endswith(".json"):
            fmt = "json"
        else:   # tanpa ekstensi: ikuti filter yang dipilih
            fmt, ext = (("csv", ".csv") if chosen == csv_f else ("json", ".json") if chosen == json_f
                        else ("excel", ".xlsx"))
            file_path += ext
        run_task(
            api_client.download_file,
            on_success=lambda _r: self.status_label.setText(f"Export disimpan ke {file_path}"),
            on_error=self._on_write_error,
            path=f"{BASE}/export",
            save_path=file_path,
            params={"format": fmt, "include_inactive": True},
        )

    # ------------------------------------------------------------------
    # PERSETUJUAN (MAKER-CHECKER)
    # ------------------------------------------------------------------
    _CR_ACTION = {"delete": "Hapus / Arsip", "unlock": "Buka Kunci"}
    _CR_STATUS = {"pending": "Menunggu", "processing": "Diproses", "approved": "Disetujui",
                  "rejected": "Ditolak", "cancelled": "Dibatalkan"}

    def _show_approvals(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Persetujuan Perubahan COA (Maker-Checker)")
        dlg.resize(1000, 480)
        lay = QVBoxLayout(dlg)
        top = QHBoxLayout()
        top.addWidget(QLabel("Tampilkan:"))
        flt = QComboBox()
        flt.addItem("Menunggu persetujuan", "pending")
        flt.addItem("Semua", "")
        flt.addItem("Disetujui", "approved")
        flt.addItem("Ditolak", "rejected")
        flt.addItem("Dibatalkan", "cancelled")
        top.addWidget(flt)
        top.addStretch()
        lay.addLayout(top)
        info = QLabel("Pemisahan tugas: Anda tidak dapat menyetujui/menolak permintaan yang Anda ajukan sendiri.")
        info.setStyleSheet("color:#6B7280; font-size:12px;")
        lay.addWidget(info)
        table = QTableWidget(0, 7)
        table.setHorizontalHeaderLabels(["Diajukan", "Akun", "Aksi", "Alasan", "Pengaju", "Status", "Keputusan"])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(table)
        btns = QHBoxLayout()
        approve = QPushButton("✔ Setujui")
        reject = QPushButton("✖ Tolak")
        cancel = QPushButton("↩ Batalkan (pengaju)")
        reload_b = QPushButton("⟳ Muat ulang")
        close = QPushButton("Tutup")
        for b in (approve, reject, cancel, reload_b):
            btns.addWidget(b)
        btns.addStretch()
        btns.addWidget(close)
        lay.addLayout(btns)
        state: dict[str, Any] = {"rows": []}

        def load() -> None:
            params = {"status": flt.currentData()} if flt.currentData() else None
            run_task(api_client.get, on_success=fill, on_error=self._on_write_error,
                     path=f"{BASE}/change-requests", params=params)

        def fill(rows: Any) -> None:
            rows = rows if isinstance(rows, list) else []
            state["rows"] = rows
            table.setRowCount(len(rows))
            for r, x in enumerate(rows):
                decided = "-"
                if x.get("decided_at"):
                    decided = f"{x.get('decided_by_name') or '-'} · {format_datetime(x.get('decided_at'))}"
                    if x.get("decision_note"):
                        decided += f" · {x['decision_note']}"
                vals = [
                    format_datetime(x.get("requested_at")), x.get("account_code"),
                    self._CR_ACTION.get(x.get("action"), x.get("action")), x.get("reason") or "-",
                    x.get("requested_by_name") or str(x.get("requested_by") or "-")[:8],
                    self._CR_STATUS.get(x.get("status"), x.get("status")), decided,
                ]
                for c, v in enumerate(vals):
                    table.setItem(r, c, QTableWidgetItem("-" if v in (None, "") else str(v)))
            table.resizeColumnsToContents()

        def current() -> dict[str, Any] | None:
            row = table.currentRow()
            if row < 0 or row >= len(state["rows"]):
                QMessageBox.information(dlg, "Info", "Pilih satu permintaan terlebih dahulu.")
                return None
            return state["rows"][row]

        def act(kind: str, label: str, ask_note: bool) -> None:
            x = current()
            if not x:
                return
            note = ""
            if ask_note:
                note, ok = QInputDialog.getText(dlg, label, "Catatan keputusan (opsional untuk setuju, wajib untuk tolak):")
                if not ok or (kind == "reject" and not note.strip()):
                    return
            elif QMessageBox.question(dlg, label, f"{label} permintaan untuk akun {x.get('account_code')}?") != QMessageBox.Yes:
                return
            run_task(
                api_client.post,
                on_success=lambda r: (QMessageBox.information(
                    dlg, label, (r or {}).get("message") or "Berhasil." if isinstance(r, dict) else "Berhasil."),
                    load(), self.refresh()),
                on_error=lambda m: QMessageBox.warning(dlg, "Gagal", m),
                path=f"{BASE}/change-requests/{x.get('id')}/{kind}",
                params={"note": note.strip()} if note else None,
            )

        approve.clicked.connect(lambda: act("approve", "Setujui", True))
        reject.clicked.connect(lambda: act("reject", "Tolak", True))
        cancel.clicked.connect(lambda: act("cancel", "Batalkan", False))
        reload_b.clicked.connect(load)
        flt.currentIndexChanged.connect(lambda _i: load())
        close.clicked.connect(dlg.accept)
        load()
        dlg.exec()

    # ------------------------------------------------------------------
    def _after_write(self, message: str) -> None:
        self.status_label.setText(message)
        self.refresh()

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        