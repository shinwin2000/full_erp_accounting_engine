#!/usr/bin/env python3
"""
smoke_test.py
==============
Verifikasi cepat instalasi frontend sebelum deploy ke produksi. Menguji:
  1. Semua dependency ter-install
  2. Semua modul registry punya halaman yang bisa dibuat tanpa error
  3. MainWindow bisa dibangun lengkap dengan seluruh navigasi

Tidak butuh koneksi ke backend (error koneksi API dianggap normal di
tahap ini — yang diuji adalah apakah UI-nya bisa dibuat tanpa exception
Python/Qt).

CARA PAKAI:
    python smoke_test.py

Exit code 0 = semua lolos. Exit code 1 = ada yang gagal (lihat detail).
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen" if "--offscreen" in sys.argv else os.environ.get("QT_QPA_PLATFORM", ""))


def main() -> int:
    print("=" * 70)
    print("  SOVEREIGN ERP DESKTOP — SMOKE TEST")
    print("=" * 70)

    # ------------------------------------------------------------------
    print("\n[1/4] Cek dependency...")
    missing = []
    for pkg in ("PySide6", "requests"):
        try:
            __import__(pkg)
            print(f"  ✅ {pkg}")
        except ImportError:
            missing.append(pkg)
            print(f"  ❌ {pkg} TIDAK TERPASANG")
    if missing:
        print(f"\nInstall dulu: pip install {' '.join(missing)}")
        return 1

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    # ------------------------------------------------------------------
    print("\n[2/4] Cek registry modul...")
    try:
        from registry.module_registry import MODULES, CATEGORY_ORDER
        print(f"  ✅ {len(MODULES)} modul terdaftar di {len(CATEGORY_ORDER)} kategori")
    except Exception as e:
        print(f"  ❌ Gagal load registry: {e}")
        return 1

    # ------------------------------------------------------------------
    print("\n[3/4] Instansiasi semua halaman...")
    from ui.main_window import MODULE_PAGE_MAP
    import importlib

    errors: list[tuple[str, str]] = []
    tested = 0

    CUSTOM_PAGES = {
        "dashboard": ("ui.pages.dashboard_page", "DashboardPage"),
        "journals": ("ui.pages.journal_page", "JournalPage"),
        "coa": ("ui.pages.coa_page", "CoaPage"),
        "ledger": ("ui.pages.ledger_page", "LedgerPage"),
        "approvals": ("ui.pages.approvals_page", "ApprovalsPage"),
        "capital": ("ui.pages.capital_page", "CapitalPage"),
        "settings": ("ui.pages.settings_page", "SettingsPage"),
        "iam_roles": ("ui.pages.iam_roles_page", "IamRolesPage"),
        "bank_reconciliation": ("ui.pages.bank_reconciliation_page", "BankReconciliationPage"),
        "stock_opname": ("ui.pages.stock_opname_page", "StockOpnamePage"),
        "documents": ("ui.pages.documents_page", "DocumentsPage"),
        "tax_spt": ("ui.pages.tax_spt_page", "TaxSptPage"),
        "payroll_salary": ("ui.pages.payroll_salary_page", "PayrollSalaryPage"),
        "goods_receipt": ("ui.pages.goods_receipt_page", "GoodsReceiptPage"),
        "consolidation_run": ("ui.pages.consolidation_run_page", "ConsolidationRunPage"),
        "approval_matrix": ("ui.pages.approval_matrix_page", "ApprovalMatrixPage"),
        "audit_forensic": ("ui.pages.audit_forensic_page", "AuditForensicPage"),
        "budget_advanced": ("ui.pages.budget_advanced_page", "BudgetAdvancedPage"),
        "asset_lifecycle": ("ui.pages.asset_lifecycle_page", "AssetLifecyclePage"),
        "hedge_advanced": ("ui.pages.hedge_advanced_page", "HedgeAdvancedPage"),
        "iam_security": ("ui.pages.iam_security_page", "IamSecurityPage"),
        "maintenance_schedule": ("ui.pages.maintenance_schedule_page", "MaintenanceSchedulePage"),
        "manufacturing_advanced": ("ui.pages.manufacturing_advanced_page", "ManufacturingAdvancedPage"),
        "project_advanced": ("ui.pages.project_advanced_page", "ProjectAdvancedPage"),
        "report_generation": ("ui.pages.report_generation_page", "ReportGenerationPage"),
        "umkm_advanced": ("ui.pages.umkm_advanced_page", "UmkmAdvancedPage"),
        "bom": ("ui.pages.bom_routing_page", "BomRoutingPage"),
        "routing": ("ui.pages.bom_routing_page", "BomRoutingPage"),
    }

    for key, (mod_path, cls_name) in {**CUSTOM_PAGES, **MODULE_PAGE_MAP}.items():
        tested += 1
        try:
            mod = importlib.import_module(mod_path)
            cls = getattr(mod, cls_name)
            cls()
        except Exception as e:
            errors.append((key, str(e)))

    # AR/AP shared workspace + forex/currency-exchange shared workspace
    try:
        from ui.pages.invoice_workspace import InvoiceWorkspacePage, AR_CONFIG, AP_CONFIG
        InvoiceWorkspacePage(AR_CONFIG)
        InvoiceWorkspacePage(AP_CONFIG)
        tested += 2
    except Exception as e:
        errors.append(("invoice_workspace", str(e)))

    try:
        from ui.pages.forex_workspace_page import ForexWorkspacePage, CURRENCY_EXCHANGE_CONFIG, FOREX_CONFIG
        ForexWorkspacePage(CURRENCY_EXCHANGE_CONFIG)
        ForexWorkspacePage(FOREX_CONFIG)
        tested += 2
    except Exception as e:
        errors.append(("forex_workspace", str(e)))

    try:
        from ui.pages.order_workspace_page import OrderWorkspacePage, PO_CONFIG, SO_CONFIG
        OrderWorkspacePage(PO_CONFIG)
        OrderWorkspacePage(SO_CONFIG)
        tested += 2
    except Exception as e:
        errors.append(("order_workspace", str(e)))

    if errors:
        print(f"  ❌ {len(errors)}/{tested} halaman GAGAL dibuat:")
        for key, err in errors:
            print(f"      - {key}: {err}")
    else:
        print(f"  ✅ Semua {tested} halaman berhasil dibuat tanpa error")

    # ------------------------------------------------------------------
    print("\n[4/4] Instansiasi MainWindow lengkap...")
    try:
        from ui.main_window import MainWindow
        mw = MainWindow()
        print(f"  ✅ MainWindow OK — {mw.nav_tree.topLevelItemCount()} kategori navigasi")
    except Exception as e:
        errors.append(("MainWindow", str(e)))
        print(f"  ❌ MainWindow gagal: {e}")

    print("\n" + "=" * 70)
    if errors:
        print(f"  HASIL: GAGAL — {len(errors)} error ditemukan. Perbaiki sebelum deploy.")
        print("=" * 70)
        return 1
    print("  HASIL: SEMUA LOLOS — aplikasi siap dijalankan.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
