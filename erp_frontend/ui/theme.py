"""
ui/theme.py
===========
Palet warna & stylesheet (QSS) global. Tema terang, profesional, khas
aplikasi ERP/akuntansi (biru navy + aksen hijau untuk status positif).
"""
from __future__ import annotations

COLORS = {
    "primary": "#1E3A8A",
    "primary_light": "#3B5FCB",
    "primary_dark": "#152A63",
    "accent": "#2563EB",
    "success": "#059669",
    "danger": "#DC2626",
    "warning": "#D97706",
    "bg": "#F3F4F6",
    "surface": "#FFFFFF",
    "border": "#E5E7EB",
    "text": "#111827",
    "text_muted": "#6B7280",
    "sidebar_bg": "#111827",
    "sidebar_text": "#D1D5DB",
    "sidebar_active": "#1E3A8A",
}

QSS = f"""
* {{
    font-family: "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
    color: {COLORS['text']};
}}

QMainWindow, QWidget#centralWidget {{
    background-color: {COLORS['bg']};
}}

/* ---------- Sidebar ---------- */
QWidget#sidebar {{
    background-color: {COLORS['sidebar_bg']};
}}
QLabel#sidebarBrand {{
    color: #FFFFFF;
    font-size: 16px;
    font-weight: 700;
    padding: 18px 16px 4px 16px;
}}
QLabel#sidebarSubBrand {{
    color: #9CA3AF;
    font-size: 11px;
    padding: 0px 16px 14px 16px;
}}
QTreeWidget#navTree {{
    background-color: {COLORS['sidebar_bg']};
    border: none;
    outline: 0;
    color: {COLORS['sidebar_text']};
    padding: 4px;
}}
QTreeWidget#navTree::item {{
    padding: 7px 6px;
    border-radius: 6px;
    margin: 1px 4px;
}}
QTreeWidget#navTree::item:hover {{
    background-color: #1F2937;
}}
QTreeWidget#navTree::item:selected {{
    background-color: {COLORS['sidebar_active']};
    color: #FFFFFF;
}}
QTreeWidget#navTree::branch {{
    background: transparent;
}}

/* ---------- Topbar ---------- */
QWidget#topbar {{
    background-color: {COLORS['surface']};
    border-bottom: 1px solid {COLORS['border']};
}}
QLabel#pageTitle {{
    font-size: 18px;
    font-weight: 700;
    color: {COLORS['text']};
}}
QLabel#userBadge {{
    color: {COLORS['text_muted']};
    font-size: 12px;
}}

/* ---------- Cards ---------- */
QFrame.card {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 10px;
}}

/* ---------- Buttons ---------- */
QPushButton {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 7px 14px;
    color: {COLORS['text']};
}}
QPushButton:hover {{
    background-color: #F9FAFB;
    border-color: {COLORS['accent']};
}}
QPushButton:disabled {{
    color: #9CA3AF;
    background-color: #F3F4F6;
}}
QPushButton#primaryButton, QPushButton.primary {{
    background-color: {COLORS['accent']};
    border-color: {COLORS['accent']};
    color: white;
    font-weight: 600;
}}
QPushButton#primaryButton:hover, QPushButton.primary:hover {{
    background-color: {COLORS['primary_light']};
}}
QPushButton.success {{
    background-color: {COLORS['success']};
    border-color: {COLORS['success']};
    color: white;
    font-weight: 600;
}}
QPushButton.success:hover {{ background-color: #047857; }}
QPushButton.danger {{
    background-color: {COLORS['danger']};
    border-color: {COLORS['danger']};
    color: white;
    font-weight: 600;
}}
QPushButton.danger:hover {{ background-color: #B91C1C; }}

/* ---------- Inputs ---------- */
QLineEdit, QComboBox, QDateEdit, QDateTimeEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {COLORS['accent']};
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {COLORS['accent']};
}}

/* ---------- Table ---------- */
QTableView {{
    background-color: {COLORS['surface']};
    alternate-background-color: #FAFAFB;
    gridline-color: {COLORS['border']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    selection-background-color: #DBEAFE;
    selection-color: {COLORS['text']};
}}
QHeaderView::section {{
    background-color: #F9FAFB;
    color: {COLORS['text_muted']};
    padding: 8px;
    border: none;
    border-bottom: 1px solid {COLORS['border']};
    font-weight: 600;
}}

/* ---------- Tabs ---------- */
QTabWidget::pane {{
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    top: -1px;
    background-color: {COLORS['surface']};
}}
QTabBar::tab {{
    background: transparent;
    padding: 8px 16px;
    color: {COLORS['text_muted']};
}}
QTabBar::tab:selected {{
    color: {COLORS['accent']};
    font-weight: 600;
    border-bottom: 2px solid {COLORS['accent']};
}}

/* ---------- Misc ---------- */
QStatusBar {{
    background: {COLORS['surface']};
    border-top: 1px solid {COLORS['border']};
}}
QToolTip {{
    background-color: #111827;
    color: white;
    border: none;
    padding: 4px 8px;
    border-radius: 4px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: #D1D5DB;
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: #9CA3AF; }}
"""
