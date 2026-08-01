"""
ui/theme.py
===========
Tema berwarna-warni (colorful theme), hanya menggunakan properti QSS yang
didukung Qt. Terinspirasi dari palet: sidebar ungu gradasi, banner ungu,
kartu KPI gradasi warna-warni, dan tombol quick-action berwarna solid.
"""
from __future__ import annotations

# Palet warna utama dipakai berulang di seluruh app (dashboard, kpi_card, dll)
PALETTE = {
    "purple_dark": "#4C1D95",
    "purple": "#6D28D9",
    "purple_light": "#8B5CF6",
    "indigo": "#4338CA",
    "blue": "#2563EB",
    "sky": "#0EA5E9",
    "teal": "#0D9488",
    "green": "#059669",
    "green_light": "#10B981",
    "amber": "#D97706",
    "orange": "#EA580C",
    "red": "#DC2626",
    "maroon": "#9F1239",
    "pink": "#DB2777",
}

# Gradasi siap-pakai untuk kartu KPI & banner (start, end)
GRADIENTS = {
    "green": ("#22C55E", "#0D9488"),
    "rose": ("#F43F5E", "#9F1239"),
    "orange": ("#F59E0B", "#DB2777"),
    "maroon": ("#7F1D1D", "#B91C1C"),
    "violet": ("#C084FC", "#7C3AED"),
    "teal": ("#2DD4BF", "#0F766E"),
    "blue": ("#38BDF8", "#2563EB"),
    "indigo": ("#818CF8", "#4338CA"),
    "purple_banner": ("#7C3AED", "#4338CA"),
}

QSS = """
/* ===== BACKGROUND UTAMA ===== */
QWidget#centralWidget {
    background-color: #EEF2FF;
}
QStackedWidget {
    background-color: #EEF2FF;
}
QScrollArea {
    background: transparent;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}

/* ===== SIDEBAR (gradasi ungu, versi lebih cerah) ===== */
QWidget#sidebar {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #6D28D9, stop:0.5 #7C3AED, stop:1 #9333EA);
    border-right: 1px solid #6D28D9;
}
QLabel#sidebarBrand {
    color: white;
    font-size: 16px;
    font-weight: bold;
    padding: 18px 16px 4px 16px;
}
QLabel#sidebarSubBrand {
    color: #EDE9FE;
    font-size: 11px;
    padding: 0px 16px 14px 16px;
    border-bottom: 1px solid rgba(255,255,255,0.18);
}
QTreeWidget#navTree {
    background-color: transparent;
    border: none;
    color: #F3E8FF;
    padding: 6px;
    outline: none;
}
QTreeWidget#navTree::item {
    padding: 7px 6px;
    border-radius: 8px;
    margin: 1px 6px;
}
QTreeWidget#navTree::item:hover {
    background-color: rgba(255,255,255,0.16);
    color: white;
}
QTreeWidget#navTree::item:selected {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #F472B6, stop:1 #A78BFA);
    color: white;
    font-weight: 600;
}
QTreeWidget#navTree::branch {
    background: transparent;
}

/* ===== TOPBAR ===== */
QWidget#topbar {
    background-color: white;
    border-bottom: 1px solid #E2E8F0;
}
QLabel#pageTitle {
    font-size: 18px;
    font-weight: bold;
    color: #1E1B4B;
}
QLabel#userBadge {
    color: #64748B;
    font-size: 12px;
}

/* Pill badges di topbar, mis. "Database Connected" / "Admin User" */
QLabel#pillSuccess {
    background-color: #DCFCE7;
    color: #15803D;
    font-size: 11px;
    font-weight: 600;
    padding: 5px 12px;
    border-radius: 11px;
    border: 1px solid #86EFAC;
}
QLabel#pillInfo {
    background-color: #DBEAFE;
    color: #1D4ED8;
    font-size: 11px;
    font-weight: 600;
    padding: 5px 12px;
    border-radius: 11px;
    border: 1px solid #93C5FD;
}

/* ===== CARD (generik, dipakai login & panel) ===== */
QFrame#card, QFrame[class="card"] {
    background-color: white;
    border: 1px solid #E9D5FF;
    border-radius: 14px;
}

/* ===== BUTTONS ===== */
QPushButton {
    background-color: white;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 7px 16px;
    color: #1E1B4B;
}
QPushButton:hover {
    background-color: #F5F3FF;
    border-color: #8B5CF6;
}
QPushButton#primaryButton, QPushButton.primary {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #6D28D9, stop:1 #2563EB);
    border: none;
    color: white;
    font-weight: 600;
}
QPushButton#primaryButton:hover, QPushButton.primary:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #7C3AED, stop:1 #3B82F6);
}
QPushButton.success {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #16A34A, stop:1 #0D9488);
    border: none;
    color: white;
    font-weight: 600;
}
QPushButton.success:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #22C55E, stop:1 #14B8A6);
}
QPushButton.danger {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #DC2626, stop:1 #9F1239);
    border: none;
    color: white;
    font-weight: 600;
}
QPushButton.danger:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #EF4444, stop:1 #BE123C);
}
QPushButton.warning {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #F59E0B, stop:1 #EA580C);
    border: none;
    color: white;
    font-weight: 600;
}
QPushButton.warning:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #FBBF24, stop:1 #F97316);
}
QPushButton.accent {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #8B5CF6, stop:1 #DB2777);
    border: none;
    color: white;
    font-weight: 600;
}
QPushButton.accent:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #A78BFA, stop:1 #EC4899);
}
QPushButton.info {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #0EA5E9, stop:1 #2563EB);
    border: none;
    color: white;
    font-weight: 600;
}
QPushButton.info:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #38BDF8, stop:1 #3B82F6);
}

/* ===== INPUTS ===== */
QLineEdit, QComboBox, QDateEdit, QDateTimeEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {
    background-color: white;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 6px 9px;
}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #8B5CF6;
}

/* ===== TABLES ===== */
QTableView {
    background-color: white;
    gridline-color: #EDE9FE;
    border: 1px solid #E9D5FF;
    border-radius: 10px;
    alternate-background-color: #FAF5FF;
}
QHeaderView::section {
    background-color: #F1E9FE;
    color: #5B21B6;
    padding: 9px;
    border: none;
    border-bottom: 2px solid #DDD6FE;
    font-weight: 600;
}
QTableView::item:selected {
    background-color: #DDD6FE;
    color: #1E1B4B;
}

/* ===== TABS ===== */
QTabWidget::pane {
    border: 1px solid #E9D5FF;
    border-radius: 8px;
    background-color: white;
}
QTabBar::tab {
    background: transparent;
    padding: 7px 18px;
    color: #64748B;
}
QTabBar::tab:selected {
    color: #7C3AED;
    font-weight: 600;
    border-bottom: 2px solid #7C3AED;
}

/* ===== MISC ===== */
QStatusBar {
    background: white;
    border-top: 1px solid #E2E8F0;
}
QToolTip {
    background-color: #4C1D95;
    color: white;
    border: none;
    padding: 4px 8px;
    border-radius: 4px;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
}
QScrollBar::handle:vertical {
    background: #C4B5FD;
    border-radius: 5px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: #A78BFA;
}
"""
