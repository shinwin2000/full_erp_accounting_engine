"""
ui/pages/payroll_salary_page.py
==================================
Melengkapi gap KRITIS di modul Payroll: sebelumnya cuma ada Payroll Run,
padahal tanpa Salary Structure per karyawan, payroll run tidak bisa
menghitung gaji dengan benar. Menambahkan Salary Structure, Salary
Component, dan lihat Payslip.

Endpoint backend (base: /payroll):
  POST /salary-structure                    - set struktur gaji karyawan
  GET  /salary-structure/{employee_id}       - lihat struktur gaji karyawan
  POST /salary-components                   - tambah komponen gaji (allowance/deduction)
  GET  /payslips/{id}                        - lihat detail payslip
  POST /payslips/{id}/send                   - kirim payslip ke karyawan
  GET  /reports/payroll-summary              - ringkasan payroll
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from core.api_client import api_client
from core.formatting import format_money
from core.workers import run_task
from PySide6.QtWidgets import (
    QComboBox,
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

BASE = "/payroll"

COMPONENT_TYPES = [
    "BASIC_SALARY", "ALLOWANCE", "OVERTIME", "BONUS",
    "DEDUCTION_BPJS_KESEHATAN", "DEDUCTION_BPJS_KETENAGAKERJAAN",
    "TAX_PPH21", "OTHER_DEDUCTION", "OTHER_ALLOWANCE",
]


class PayrollSalaryPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel("💰  Struktur Gaji, Komponen & Payslip")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(SalaryStructureTab(), "Struktur Gaji")
        self.tabs.addTab(SalaryComponentTab(), "Komponen Gaji")
        self.tabs.addTab(PayslipTab(), "Payslip")
        self.tabs.addTab(PayrollSummaryTab(), "Ringkasan Payroll")
        outer.addWidget(self.tabs, stretch=1)


# ==========================================================================
class SalaryStructureTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        outer.addWidget(QLabel("<b>Lihat Struktur Gaji Karyawan</b>"))
        lookup_row = QHBoxLayout()
        self.lookup_employee_edit = QLineEdit()
        self.lookup_employee_edit.setPlaceholderText("UUID karyawan")
        lookup_row.addWidget(self.lookup_employee_edit)
        lookup_btn = QPushButton("⟳ Tampilkan")
        lookup_btn.clicked.connect(self._lookup)
        lookup_row.addWidget(lookup_btn)
        outer.addLayout(lookup_row)

        self.detail_label = QLabel("")
        self.detail_label.setWordWrap(True)
        outer.addWidget(self.detail_label)

        outer.addWidget(QLabel("<b>Set / Ubah Struktur Gaji</b>"))
        form = QFormLayout()
        self.employee_edit = QLineEdit()
        self.employee_edit.setPlaceholderText("UUID karyawan")
        form.addRow("Karyawan", self.employee_edit)
        self.basic_salary_edit = QLineEdit()
        form.addRow("Gaji Pokok", self.basic_salary_edit)
        self.deductions_edit = QTextEdit()
        self.deductions_edit.setPlaceholderText(
            'Potongan lain (opsional), format: nama=jumlah per baris. Contoh:\nkasbon=500000\nasuransi=150000'
        )
        self.deductions_edit.setFixedHeight(80)
        form.addRow("Potongan Lain", self.deductions_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("💾 Simpan Struktur Gaji")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        outer.addWidget(submit_btn)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _lookup(self) -> None:
        emp_id = self.lookup_employee_edit.text().strip()
        if not emp_id:
            QMessageBox.information(self, "Info", "Masukkan UUID karyawan.")
            return
        run_task(api_client.get, on_success=self._on_lookup_result, on_error=self._on_error,
                  path=f"{BASE}/salary-structure/{emp_id}")

    def _on_lookup_result(self, data: Any) -> None:
        data = data or {}
        basic = data.get("basic_salary")
        deductions = data.get("other_deductions", {}) or {}
        lines = [f"<b>Gaji Pokok:</b> {format_money(basic)}"]
        if deductions:
            lines.append("<b>Potongan Lain:</b>")
            for k, v in deductions.items():
                lines.append(f"&nbsp;&nbsp;{k}: {format_money(v)}")
        self.detail_label.setText("<br>".join(lines))

    def _submit(self) -> None:
        try:
            basic = Decimal(self.basic_salary_edit.text().strip())
            if basic <= 0:
                raise InvalidOperation
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Gaji pokok harus > 0.")
            return
        if not self.employee_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "Karyawan wajib diisi.")
            return

        deductions: dict[str, float] = {}
        for line in self.deductions_edit.toPlainText().strip().splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            name, _, value = line.partition("=")
            try:
                deductions[name.strip()] = float(Decimal(value.strip()))
            except InvalidOperation:
                QMessageBox.warning(self, "Validasi", f"Nilai potongan '{line}' bukan angka valid.")
                return

        payload = {
            "employee_id": self.employee_edit.text().strip(),
            "basic_salary": float(basic),
            "other_deductions": deductions or None,
        }
        run_task(api_client.post, on_success=lambda _r: self._on_saved(), on_error=self._on_error,
                  path=f"{BASE}/salary-structure", json_body=payload)

    def _on_saved(self) -> None:
        self.status_label.setText("Struktur gaji berhasil disimpan.")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal.")


# ==========================================================================
class SalaryComponentTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "<b>Tambah Komponen Gaji</b><br>"
            "<span style='color:#6B7280;'>Untuk tunjangan (allowance), bonus, lembur, atau potongan tambahan "
            "di luar gaji pokok & potongan standar.</span>"
        ))
        form = QFormLayout()
        self.employee_edit = QLineEdit()
        self.employee_edit.setPlaceholderText("UUID karyawan")
        form.addRow("Karyawan", self.employee_edit)
        self.type_combo = QComboBox()
        self.type_combo.addItems(COMPONENT_TYPES)
        form.addRow("Tipe Komponen", self.type_combo)
        self.amount_edit = QLineEdit()
        form.addRow("Jumlah", self.amount_edit)
        self.desc_edit = QLineEdit()
        form.addRow("Deskripsi", self.desc_edit)
        outer.addLayout(form)

        submit_btn = QPushButton("+ Tambah Komponen")
        submit_btn.setObjectName("primaryButton")
        submit_btn.clicked.connect(self._submit)
        outer.addWidget(submit_btn)

        outer.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _submit(self) -> None:
        try:
            amount = Decimal(self.amount_edit.text().strip())
        except InvalidOperation:
            QMessageBox.warning(self, "Validasi", "Jumlah harus angka.")
            return
        if not self.employee_edit.text().strip():
            QMessageBox.warning(self, "Validasi", "Karyawan wajib diisi.")
            return
        payload = {
            "employee_id": self.employee_edit.text().strip(),
            "component_type": self.type_combo.currentText(),
            "amount": float(amount),
            "description": self.desc_edit.text().strip() or None,
        }
        run_task(api_client.post, on_success=lambda _r: self._on_saved(), on_error=self._on_error,
                  path=f"{BASE}/salary-components", json_body=payload)

    def _on_saved(self) -> None:
        self.status_label.setText("Komponen gaji berhasil ditambahkan.")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class PayslipTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        row = QHBoxLayout()
        self.payslip_id_edit = QLineEdit()
        self.payslip_id_edit.setPlaceholderText("UUID payslip (dari detail payroll run)")
        row.addWidget(self.payslip_id_edit)
        load_btn = QPushButton("⟳ Tampilkan Payslip")
        load_btn.setObjectName("primaryButton")
        load_btn.clicked.connect(self._load)
        row.addWidget(load_btn)
        send_btn = QPushButton("✉ Kirim ke Karyawan")
        send_btn.clicked.connect(self._send)
        row.addWidget(send_btn)
        outer.addLayout(row)

        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        outer.addWidget(self.detail_text, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load(self) -> None:
        pid = self.payslip_id_edit.text().strip()
        if not pid:
            QMessageBox.information(self, "Info", "Masukkan UUID payslip.")
            return
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{BASE}/payslips/{pid}")

    def _on_loaded(self, data: Any) -> None:
        data = data or {}
        lines = []
        for key, val in data.items():
            if isinstance(val, (int, float)) or (isinstance(val, str) and val.replace(".", "").isdigit()):
                lines.append(f"{key.replace('_', ' ').title()}: {format_money(val)}")
            else:
                lines.append(f"{key.replace('_', ' ').title()}: {val}")
        self.detail_text.setPlainText("\n".join(lines))
        self.status_label.setText("Payslip dimuat.")

    def _send(self) -> None:
        pid = self.payslip_id_edit.text().strip()
        if not pid:
            QMessageBox.information(self, "Info", "Masukkan UUID payslip.")
            return
        run_task(api_client.post, on_success=lambda _r: self.status_label.setText("Payslip terkirim."),
                  on_error=self._on_error, path=f"{BASE}/payslips/{pid}/send")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)


# ==========================================================================
class PayrollSummaryTab(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        row = QHBoxLayout()
        load_btn = QPushButton("⟳ Muat Ringkasan Payroll")
        load_btn.setObjectName("primaryButton")
        load_btn.clicked.connect(self._load)
        row.addWidget(load_btn)
        row.addStretch()
        outer.addLayout(row)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Keterangan", "Nilai"])
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def _load(self) -> None:
        run_task(api_client.get, on_success=self._on_loaded, on_error=self._on_error,
                  path=f"{BASE}/reports/payroll-summary")

    def _on_loaded(self, data: Any) -> None:
        data = data or {}
        rows = list(data.items())
        self.table.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(k.replace("_", " ").title()))
            self.table.setItem(r, 1, QTableWidgetItem(str(v)))
        self.table.resizeColumnsToContents()
        self.status_label.setText("Ringkasan dimuat.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")
