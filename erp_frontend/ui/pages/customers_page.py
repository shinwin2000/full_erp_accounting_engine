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
from registry.module_registry import MODULES
from ui.pages.customer_detail_dialog import CustomerDetailDialog
from ui.widgets.generic_list_page import GenericListPage

CONFIG = MODULES["customers"]


class CustomersPage(GenericListPage):
    """Halaman Pelanggan (Customer), + tombol Detail untuk data anak."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
        self._add_detail_button()

    # ------------------------------------------------------------------
    def _add_detail_button(self) -> None:
        self.detail_btn = QPushButton("📋 Detail")
        self.detail_btn.clicked.connect(self._open_detail)
        # Taruh tepat di sebelah kiri tombol "+ Baru" (toolbar row pertama
        # setelah judul, lihat GenericListPage._build_ui -> layout item ke-2).
        toolbar_layout = self.layout().itemAt(1).layout()
        insert_at = toolbar_layout.count() - 1 if self.config.can_create else toolbar_layout.count()
        toolbar_layout.insertWidget(insert_at, self.detail_btn)

    def _open_detail(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Info", "Pilih baris pelanggan terlebih dahulu.")
            return
        customer_id = record.get(self.config.id_field)
        label = record.get("customer_name") or record.get("customer_code") or str(customer_id)
        dlg = CustomerDetailDialog(str(customer_id), str(label), parent=self)
        dlg.exec()
