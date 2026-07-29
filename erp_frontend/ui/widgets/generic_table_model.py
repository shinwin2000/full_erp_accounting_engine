"""
ui/widgets/generic_table_model.py
==================================
Model tabel generik: menerima list[dict] hasil API + daftar kolom
(field, label) dan menampilkannya sebagai QTableView. Mendukung format
otomatis untuk uang, tanggal, dan status badge berdasarkan nama field.
"""
from __future__ import annotations

from typing import Any

from core.formatting import format_date, format_money, status_color
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

_MONEY_HINTS = ("amount", "cost", "price", "balance", "total", "dpp", "value", "salary", "limit", "rate")
_DATE_HINTS = ("date", "_at")


class GenericTableModel(QAbstractTableModel):
    def __init__(self, columns: list[tuple[str, str]], rows: list[dict[str, Any]] | None = None):
        super().__init__()
        self.columns = columns
        self.rows: list[dict[str, Any]] = rows or []

    # ------------------------------------------------------------------
    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def record_at(self, row: int) -> dict[str, Any]:
        return self.rows[row]

    # ------------------------------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.columns[section][1]
        return str(section + 1)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        field_name, _label = self.columns[index.column()]
        record = self.rows[index.row()]
        value = _dig(record, field_name)

        if role == Qt.DisplayRole:
            return _format_value(field_name, value)
        if role == Qt.ForegroundRole and field_name == "status" and value:
            return QColor(status_color(str(value)))
        if role == Qt.TextAlignmentRole and _looks_numeric(field_name):
            return Qt.AlignRight | Qt.AlignVCenter
        return None


def _dig(record: dict[str, Any], field_name: str) -> Any:
    if field_name in record:
        return record[field_name]
    # dukung notasi nested "customer.name"
    if "." in field_name:
        cur: Any = record
        for part in field_name.split("."):
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return None
        return cur
    return record.get(field_name)


def _looks_numeric(field_name: str) -> bool:
    fn = field_name.lower()
    return any(h in fn for h in _MONEY_HINTS) or fn in ("quantity", "qty", "hours", "rate")


def _format_value(field_name: str, value: Any) -> str:
    if value is None:
        return "-"
    fn = field_name.lower()
    if isinstance(value, bool):
        return "Ya" if value else "Tidak"
    if any(h in fn for h in _MONEY_HINTS):
        return format_money(value)
    if any(h in fn for h in _DATE_HINTS):
        return format_date(value)
    if isinstance(value, (list, dict)):
        return str(len(value)) + " item" if isinstance(value, list) else str(value)
    return str(value)
