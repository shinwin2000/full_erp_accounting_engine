"""
ui/main_window.py
====================
Jendela utama aplikasi setelah login. Berisi:
  - Sidebar (QTreeWidget) navigasi ke seluruh modul, dikelompokkan per
    kategori sesuai registry/module_registry.py
  - Topbar: judul halaman aktif + info user + tombol ganti entitas/logout
  - QStackedWidget konten, dengan lazy-loading (halaman dibuat saat
    pertama kali dibuka, lalu di-cache)
"""
from __future__ import annotations

import importlib
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.api_client import api_client
from core.config import APP_NAME, APP_VERSION
from core.session import session
from core.workers import run_task
from registry.module_registry import CATEGORY_ORDER, MODULES, modules_by_category

NAV_ROLE = Qt.UserRole + 1

# Peta modul -> (module_path, class_name) untuk 37 modul yang punya file
# halaman khusus sendiri di ui/pages/<key>_page.py. 8 modul lain (journals,
# coa, ledger, ar, ap, approvals, capital, settings) ditangani langsung di
# _build_page() karena UI-nya benar-benar kustom (bukan CRUD sederhana).
MODULE_PAGE_MAP: dict[str, tuple[str, str]] = {
    "fiscal_periods": ("ui.pages.fiscal_periods_page", "FiscalPeriodsPage"),
    "customers": ("ui.pages.customers_page", "CustomersPage"),
    "suppliers": ("ui.pages.suppliers_page", "SuppliersPage"),
    "employees": ("ui.pages.employees_page", "EmployeesPage"),
    "legal_entities": ("ui.pages.legal_entities_page", "LegalEntitiesPage"),
    "iam_users": ("ui.pages.iam_users_page", "IamUsersPage"),
    "bank_accounts": ("ui.pages.bank_accounts_page", "BankAccountsPage"),
    "bank_transactions": ("ui.pages.bank_transactions_page", "BankTransactionsPage"),
    "fixed_assets": ("ui.pages.fixed_assets_page", "FixedAssetsPage"),
    "intangible_assets": ("ui.pages.intangible_assets_page", "IntangibleAssetsPage"),
    "goodwill": ("ui.pages.goodwill_page", "GoodwillPage"),
    "maintenance_assets": ("ui.pages.maintenance_assets_page", "MaintenanceAssetsPage"),
    "maintenance_work_orders": ("ui.pages.maintenance_work_orders_page", "MaintenanceWorkOrdersPage"),
    "inventory_items": ("ui.pages.inventory_items_page", "InventoryItemsPage"),
    "stock_movements": ("ui.pages.stock_movements_page", "StockMovementsPage"),
    "warehouses": ("ui.pages.warehouses_page", "WarehousesPage"),
    # bom & routing: ditangani branch eksplisit di _build_page (butuh tab gabungan)
    "work_orders": ("ui.pages.work_orders_page", "WorkOrdersPage"),
    # purchase_orders & sales_orders: ditangani branch eksplisit di _build_page
    # (butuh config PO_CONFIG/SO_CONFIG, bukan konstruktor tanpa argumen)
    "projects": ("ui.pages.projects_page", "ProjectsPage"),
    "time_entries": ("ui.pages.time_entries_page", "TimeEntriesPage"),
    "exchange_rates": ("ui.pages.exchange_rates_page", "ExchangeRatesPage"),
    "forex": ("ui.pages.forex_page", "ForexPage"),
    "hedge_derivatives": ("ui.pages.hedge_derivatives_page", "HedgeDerivativesPage"),
    "hedge_relationships": ("ui.pages.hedge_relationships_page", "HedgeRelationshipsPage"),
    "consolidation_groups": ("ui.pages.consolidation_groups_page", "ConsolidationGroupsPage"),
    "intercompany": ("ui.pages.intercompany_page", "IntercompanyPage"),
    "payroll_runs": ("ui.pages.payroll_runs_page", "PayrollRunsPage"),
    "budgets": ("ui.pages.budgets_page", "BudgetsPage"),
    "tax_faktur": ("ui.pages.tax_faktur_page", "TaxFakturPage"),
    "documents": ("ui.pages.documents_page", "DocumentsPage"),
    "reports": ("ui.pages.reports_page", "ReportsPage"),
    "audit": ("ui.pages.audit_page", "AuditPage"),
    "umkm": ("ui.pages.umkm_page", "UmkmPage"),
    "payments": ("ui.pages.payments_page", "PaymentsPage"),
}


class MainWindow(QMainWindow):
    logout_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1440, 900)
        self._page_cache: dict[str, QWidget] = {}
        self._build_ui()
        self._populate_nav()
        self._select_dashboard()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ---------- Sidebar ----------
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(280)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        brand = QLabel("🏛️ Sovereign ERP")
        brand.setObjectName("sidebarBrand")
        sidebar_layout.addWidget(brand)

        sub_brand = QLabel(f"Accounting Engine v{APP_VERSION}")
        sub_brand.setObjectName("sidebarSubBrand")
        sidebar_layout.addWidget(sub_brand)

        self.nav_tree = QTreeWidget()
        self.nav_tree.setObjectName("navTree")
        self.nav_tree.setHeaderHidden(True)
        self.nav_tree.itemClicked.connect(self._on_nav_clicked)
        sidebar_layout.addWidget(self.nav_tree, stretch=1)

        root_layout.addWidget(sidebar)

        # ---------- Right side: topbar + content ----------
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        topbar = QWidget()
        topbar.setObjectName("topbar")
        topbar.setFixedHeight(56)
        topbar_layout = QHBoxLayout(topbar)
        topbar_layout.setContentsMargins(20, 0, 20, 0)

        self.page_title = QLabel("Dashboard")
        self.page_title.setObjectName("pageTitle")
        topbar_layout.addWidget(self.page_title)
        topbar_layout.addStretch()

        self.entity_combo = QComboBox()
        self.entity_combo.setMinimumWidth(200)
        self.entity_combo.setVisible(False)
        topbar_layout.addWidget(self.entity_combo)

        self.user_badge = QLabel("")
        self.user_badge.setObjectName("userBadge")
        topbar_layout.addWidget(self.user_badge)

        logout_btn = QPushButton("Keluar")
        logout_btn.clicked.connect(self._on_logout)
        topbar_layout.addWidget(logout_btn)

        right_layout.addWidget(topbar)

        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, stretch=1)

        root_layout.addWidget(right, stretch=1)

        self._refresh_user_badge()

    def _refresh_user_badge(self) -> None:
        self.user_badge.setText(f"👤 {session.display_name}")

    # ------------------------------------------------------------------
    def _populate_nav(self) -> None:
        dashboard_item = QTreeWidgetItem(["🏠  Dashboard"])
        dashboard_item.setData(0, NAV_ROLE, ("dashboard", None))
        self.nav_tree.addTopLevelItem(dashboard_item)

        by_category = modules_by_category()
        categories = CATEGORY_ORDER + [c for c in by_category if c not in CATEGORY_ORDER]

        for category in categories:
            configs = by_category.get(category)
            if not configs:
                continue
            cat_item = QTreeWidgetItem([category])
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemIsSelectable)
            self.nav_tree.addTopLevelItem(cat_item)
            for cfg in sorted(configs, key=lambda c: c.label):
                child = QTreeWidgetItem([f"{cfg.icon}  {cfg.label}"])
                child.setData(0, NAV_ROLE, ("module", cfg.key))
                cat_item.addChild(child)
            cat_item.setExpanded(True)

    def _select_dashboard(self) -> None:
        self._open_page("dashboard", None, "Dashboard")

    def _on_nav_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        payload = item.data(0, NAV_ROLE)
        if not payload:
            return
        kind, key = payload
        label = item.text(0).strip()
        # buang emoji prefix untuk judul halaman
        parts = label.split("  ", 1)
        title = parts[1] if len(parts) > 1 else label
        self._open_page(kind, key, title)

    # ------------------------------------------------------------------
    def _open_page(self, kind: str, key: Optional[str], title: str) -> None:
        cache_key = f"{kind}:{key}"
        if cache_key not in self._page_cache:
            widget = self._build_page(kind, key)
            self._page_cache[cache_key] = widget
            self.stack.addWidget(widget)
        self.stack.setCurrentWidget(self._page_cache[cache_key])
        self.page_title.setText(title)

    def _build_page(self, kind: str, key: Optional[str]) -> QWidget:
        if kind == "dashboard":
            from ui.pages.dashboard_page import DashboardPage
            return DashboardPage()

        if kind == "module":
            if key == "journals":
                from ui.pages.journal_page import JournalPage
                return JournalPage()
            if key == "coa":
                from ui.pages.coa_page import CoaPage
                return CoaPage()
            if key == "ledger":
                from ui.pages.ledger_page import LedgerPage
                return LedgerPage()
            if key == "ar":
                from ui.pages.invoice_workspace import InvoiceWorkspacePage, AR_CONFIG
                return InvoiceWorkspacePage(AR_CONFIG)
            if key == "ap":
                from ui.pages.invoice_workspace import InvoiceWorkspacePage, AP_CONFIG
                return InvoiceWorkspacePage(AP_CONFIG)
            if key == "approvals":
                from ui.pages.approvals_page import ApprovalsPage
                return ApprovalsPage()
            if key == "capital":
                from ui.pages.capital_page import CapitalPage
                return CapitalPage()
            if key == "settings":
                from ui.pages.settings_page import SettingsPage
                return SettingsPage()
            if key == "iam_roles":
                from ui.pages.iam_roles_page import IamRolesPage
                return IamRolesPage()
            if key == "bank_reconciliation":
                from ui.pages.bank_reconciliation_page import BankReconciliationPage
                return BankReconciliationPage()
            if key == "stock_opname":
                from ui.pages.stock_opname_page import StockOpnamePage
                return StockOpnamePage()
            if key == "documents":
                from ui.pages.documents_page import DocumentsPage
                return DocumentsPage()
            if key == "tax_spt":
                from ui.pages.tax_spt_page import TaxSptPage
                return TaxSptPage()
            if key == "payroll_salary":
                from ui.pages.payroll_salary_page import PayrollSalaryPage
                return PayrollSalaryPage()
            if key == "goods_receipt":
                from ui.pages.goods_receipt_page import GoodsReceiptPage
                return GoodsReceiptPage()
            if key == "consolidation_run":
                from ui.pages.consolidation_run_page import ConsolidationRunPage
                return ConsolidationRunPage()
            if key == "approval_matrix":
                from ui.pages.approval_matrix_page import ApprovalMatrixPage
                return ApprovalMatrixPage()
            if key == "audit_forensic":
                from ui.pages.audit_forensic_page import AuditForensicPage
                return AuditForensicPage()
            if key == "budget_advanced":
                from ui.pages.budget_advanced_page import BudgetAdvancedPage
                return BudgetAdvancedPage()
            if key == "currency_exchange_advanced":
                from ui.pages.forex_workspace_page import ForexWorkspacePage, CURRENCY_EXCHANGE_CONFIG
                return ForexWorkspacePage(CURRENCY_EXCHANGE_CONFIG)
            if key == "forex_advanced":
                from ui.pages.forex_workspace_page import ForexWorkspacePage, FOREX_CONFIG
                return ForexWorkspacePage(FOREX_CONFIG)
            if key == "asset_lifecycle":
                from ui.pages.asset_lifecycle_page import AssetLifecyclePage
                return AssetLifecyclePage()
            if key == "hedge_advanced":
                from ui.pages.hedge_advanced_page import HedgeAdvancedPage
                return HedgeAdvancedPage()
            if key == "iam_security":
                from ui.pages.iam_security_page import IamSecurityPage
                return IamSecurityPage()
            if key == "maintenance_schedule":
                from ui.pages.maintenance_schedule_page import MaintenanceSchedulePage
                return MaintenanceSchedulePage()
            if key == "manufacturing_advanced":
                from ui.pages.manufacturing_advanced_page import ManufacturingAdvancedPage
                return ManufacturingAdvancedPage()
            if key == "project_advanced":
                from ui.pages.project_advanced_page import ProjectAdvancedPage
                return ProjectAdvancedPage()
            if key == "report_generation":
                from ui.pages.report_generation_page import ReportGenerationPage
                return ReportGenerationPage()
            if key == "umkm_advanced":
                from ui.pages.umkm_advanced_page import UmkmAdvancedPage
                return UmkmAdvancedPage()
            if key == "purchase_orders":
                from ui.pages.order_workspace_page import OrderWorkspacePage, PO_CONFIG
                return OrderWorkspacePage(PO_CONFIG)
            if key == "sales_orders":
                from ui.pages.order_workspace_page import OrderWorkspacePage, SO_CONFIG
                return OrderWorkspacePage(SO_CONFIG)
            if key in ("bom", "routing"):
                from ui.pages.bom_routing_page import BomRoutingPage
                return BomRoutingPage()

            # 37 modul lain -> masing-masing punya file halaman sendiri di
            # ui/pages/<key>_page.py (lihat MODULE_PAGE_MAP di bawah), yang
            # secara internal mewarisi GenericListPage + config registry.
            if key in MODULE_PAGE_MAP:
                module_path, class_name = MODULE_PAGE_MAP[key]
                module = importlib.import_module(module_path)
                page_class = getattr(module, class_name)
                return page_class()

            # fallback terakhir (seharusnya tidak pernah tercapai selama
            # registry & MODULE_PAGE_MAP sinkron)
            from ui.widgets.generic_list_page import GenericListPage
            cfg = MODULES[key]
            return GenericListPage(cfg)

        placeholder = QWidget()
        QVBoxLayout(placeholder).addWidget(QLabel("Halaman tidak ditemukan."))
        return placeholder

    # ------------------------------------------------------------------
    def _on_logout(self) -> None:
        confirm = QMessageBox.question(self, "Konfirmasi", "Keluar dari aplikasi?")
        if confirm != QMessageBox.Yes:
            return
        run_task(api_client.logout, on_success=lambda _r: self.logout_requested.emit(),
                  on_error=lambda _m: self.logout_requested.emit())
