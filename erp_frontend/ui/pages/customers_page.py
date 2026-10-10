"""
ui/pages/customers_page.py
=============================
Halaman modul "Pelanggan (Customer)" (Master Data).

Endpoint backend : /customers/customers

Field/kolom grid utama & form Tambah/Ubah SELALU sinkron dengan
registry/module_registry.py (sumber kebenaran tunggal) -- kalau perlu
ubah field, ubah di module_registry.py, JANGAN utak-atik CONFIG di sini.

Satu pengecualian yang memang khusus modul ini: tombol "📋 Detail" di
bawah, karena Customer punya data anak (alamat/contact person/
attachment/notes/tags/riwayat kredit/riwayat saldo -- lihat
customer_detail_dialog.py) yang tidak muat direpresentasikan sebagai
kolom grid generik.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QPushButton
from core.api_client import api_client
from core.workers import run_task
from registry.module_registry import MODULES, FieldSpec, FieldType
from ui.pages.customer_detail_dialog import CustomerDetailDialog
from ui.widgets.generic_list_page import GenericListPage
from ui.widgets.modern_form_dialog import ModernFormDialog

CONFIG = MODULES["customers"]

# Field keuangan yang TIDAK boleh diubah lewat form Ubah: backend (PATCH
# /customers/{id}) memang mengabaikannya. Limit kredit diubah lewat tombol
# "Limit Kredit" (endpoint khusus yang mencatat riwayat + alasan); saldo
# piutang berubah dari transaksi, bukan diketik manual.
_EDIT_EXCLUDED_FIELDS = ("credit_limit", "opening_balance", "currency")


class CustomersPage(GenericListPage):
    """Halaman Pelanggan (Customer), + tombol Detail untuk data anak."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
        self._add_detail_button()
        self._add_credit_limit_button()
        self._apply_permission_gates()

    # ------------------------------------------------------------------
    def _make_form_dialog(self, title, fields, initial=None):
        """Form Tambah/Ubah Pelanggan memakai tampilan modern (kartu per section)."""
        if initial:
            fields = [f for f in fields if f.name not in _EDIT_EXCLUDED_FIELDS]
            code = initial.get("customer_code") or ""
            name = initial.get("customer_name") or ""
            subtitle = " • ".join(x for x in (code, name) if x) or "Perbarui data pelanggan."
            title, icon = "Ubah Data Pelanggan", "✏️"
        else:
            subtitle = "Isi data pelanggan baru. Kode customer dibuat otomatis jika dikosongkan."
            title, icon = "Tambah Pelanggan Baru", "🧑‍💼"
        return ModernFormDialog(
            title, fields, initial=initial, parent=self,
            icon=icon, subtitle=subtitle, columns=2,
            readonly_fields=("customer_code",),
            send_empty_as_null=bool(initial),
        )

    def _add_detail_button(self) -> None:
        self.detail_btn = QPushButton("📋 Detail")
        self.detail_btn.clicked.connect(self._open_detail)
        # Taruh tepat di sebelah kiri tombol "+ Baru" (toolbar row pertama
        # setelah judul, lihat GenericListPage._build_ui -> layout item ke-2).
        toolbar_layout = self.layout().itemAt(1).layout()
        insert_at = toolbar_layout.count() - 1 if self.config.can_create else toolbar_layout.count()
        toolbar_layout.insertWidget(insert_at, self.detail_btn)

    # Tombol -> permission yang dibutuhkan (sama dengan yang ditegakkan server).
    button_permissions = (
        ("new_btn", "customer:create"),
        ("edit_btn", "customer:update"),
        ("action_btn", "customer:update"),
        ("delete_btn", "customer:delete"),
        ("credit_btn", "customer:approve"),
        ("export_btn", "customer:export"),
    )

    def _add_credit_limit_button(self) -> None:
        self.credit_btn = QPushButton("💳 Limit Kredit")
        self.credit_btn.setToolTip("Ubah limit kredit pelanggan terpilih (tercatat di Riwayat Kredit)")
        self.credit_btn.clicked.connect(self._change_credit_limit)
        toolbar_layout = self.layout().itemAt(1).layout()
        # tepat di kiri tombol "📋 Detail"
        idx = toolbar_layout.indexOf(self.detail_btn)
        toolbar_layout.insertWidget(idx if idx >= 0 else toolbar_layout.count(), self.credit_btn)
        # ikut dikunci saat proses simpan berlangsung (lihat _set_write_buttons_enabled)
        if hasattr(self, "_write_buttons"):
            self._write_buttons.append(self.credit_btn)

    def _change_credit_limit(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Info", "Pilih baris pelanggan terlebih dahulu.")
            return
        customer_id = record.get(self.config.id_field)
        try:
            current = float(record.get("credit_limit") or 0)
        except (TypeError, ValueError):
            current = 0.0
        code = record.get("customer_code") or ""
        name = record.get("customer_name") or ""
        fields = [
            FieldSpec("new_limit", "Limit Kredit Baru", FieldType.DECIMAL, required=True,
                      min_value=0, section="Limit Kredit"),
            FieldSpec("reason", "Alasan Perubahan", FieldType.TEXTAREA, required=True,
                      help_text="mis. Naik limit karena histori pembayaran baik",
                      section="Limit Kredit"),
        ]
        dlg = ModernFormDialog(
            "Ubah Limit Kredit", fields, initial={"new_limit": current}, parent=self,
            icon="💳", columns=1,
            subtitle=f"{code} • {name}  |  Limit saat ini: Rp {current:,.2f}",
        )
        if not dlg.exec():
            return
        payload = dlg.result_payload()
        self.status_label.setText("Menyimpan limit kredit...")
        self._set_write_buttons_enabled(False)
        run_task(
            api_client.post,
            on_success=lambda _r: self._after_write("Limit kredit diperbarui."),
            on_error=self._on_write_error,
            path=f"{self.config.base_path}{self.config.list_path.rstrip('/')}/{customer_id}/credit-limit",
            json_body=payload,
        )

    def _open_detail(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Info", "Pilih baris pelanggan terlebih dahulu.")
            return
        customer_id = record.get(self.config.id_field)
        label = record.get("customer_name") or record.get("customer_code") or str(customer_id)
        dlg = CustomerDetailDialog(str(customer_id), str(label), parent=self)
        dlg.exec()
        # Data di tab Detail (alamat/kontak utama) ikut mengubah data utama -> segarkan grid.
        self.refresh()
