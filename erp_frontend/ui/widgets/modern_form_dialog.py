"""
ui/widgets/modern_form_dialog.py
=================================
Dialog form versi "modern" untuk Tambah / Ubah data. Dirender otomatis dari
`list[FieldSpec]` (sama seperti FormDialog), jadi field tetap SATU sumber
kebenaran di registry/module_registry.py -- yang berubah hanya tampilan:

- Header gradasi ungu dengan ikon + judul + sub-judul.
- Tiap `section` jadi kartu putih bergaya (ikon + judul section).
- Label di ATAS input (bukan kiri-rata-kanan), grid 2 kolom rapi,
  TEXTAREA selalu selebar kartu.
- Awalan "Rp", akhiran "hari"/"%" untuk field angka, tanpa tombol spinner.
- Validasi inline: field wajib yang kosong diberi border merah + pesan di
  footer (tidak lagi popup yang mengganggu).
- Scroll mouse di atas combo/spinbox tidak lagi mengubah nilai secara tidak
  sengaja -- scroll diteruskan ke form.
- Footer tetap (tombol Batal / Simpan selalu terlihat).

API kompatibel dengan FormDialog: `exec()`, `result_payload()`, `collect()`.
Dipakai lewat `modern_factory(...)` atau langsung `ModernFormDialog(...)`.
"""
from __future__ import annotations

import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from registry.module_registry import FieldSpec, FieldType
from ui.widgets.form_dialog import FormDialog, _extract_value

_INPUT_HEIGHT = 38

# Ikon badge per judul section (fallback: "📄")
_SECTION_ICONS = {
    "Identitas": "🪪",
    "Kontak & Alamat": "📍",
    "Keuangan": "💰",
    "Lainnya": "🧩",
    "Limit Kredit": "💳",
    "Identitas Akun": "🪪",
    "Hierarki & Klasifikasi": "🌳",
    "Posting & Keuangan": "💰",
    "Kontrol & Penanda": "🛡️",
    "Keterangan": "📝",
    "Akun Salinan": "⧉",
}

# Placeholder contoh per nama field (hanya dipakai jika FieldSpec.help_text kosong)
_PLACEHOLDERS = {
    "customer_name": "mis. Budi Santoso",
    "company_name": "mis. PT Maju Jaya",
    "tax_id": "15 / 16 digit NPWP",
    "address": "Nama jalan, nomor, RT/RW, kelurahan...",
    "city": "mis. Medan",
    "province": "mis. Sumatera Utara",
    "district": "Kecamatan",
    "postal_code": "mis. 20200",
    "phone": "mis. 061-1234567",
    "mobile": "mis. 0812xxxxxxxx",
    "email": "nama@perusahaan.com",
    "website": "https://",
    "contact_person": "Nama PIC",
    "contact_phone": "No. telepon PIC",
    "contact_email": "Email PIC",
    "category": "mis. Retail, Distributor",
    "price_group": "mis. Level 1",
}

# Awalan / akhiran untuk field angka
_PREFIXES = {"credit_limit": "Rp ", "opening_balance": "Rp ", "new_limit": "Rp "}
_SUFFIXES = {"payment_term_days": " hari", "discount_percent": " %"}

_ARROW_PNG: str | None = None


def _combo_arrow_path() -> str:
    """Gambar panah dropdown (chevron) sekali ke file PNG sementara supaya bisa
    dipakai QSS -- panah bawaan hilang/glitch begitu drop-down di-style."""
    global _ARROW_PNG
    if _ARROW_PNG and Path(_ARROW_PNG).exists():
        return _ARROW_PNG
    pix = QPixmap(24, 24)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor("#6B7280"))
    pen.setWidthF(2.4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.drawPolyline([QPointF(6, 9), QPointF(12, 15), QPointF(18, 9)])
    painter.end()
    path = Path(tempfile.gettempdir()) / "erp_combo_arrow.png"
    pix.save(str(path), "PNG")
    _ARROW_PNG = path.as_posix()
    return _ARROW_PNG


def _build_qss() -> str:
    arrow = _combo_arrow_path()
    return f"""
QDialog#modernForm {{ background: #F5F5FB; }}

/* ---------- Header ---------- */
QFrame#mfHeader {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7C3AED, stop:1 #4338CA);
}}
QLabel#mfIcon {{
    background: rgba(255, 255, 255, 0.20);
    border-radius: 25px;
    min-width: 50px; max-width: 50px; min-height: 50px; max-height: 50px;
    font-size: 26px;
}}
QLabel#mfTitle {{ color: #FFFFFF; font-size: 20px; font-weight: 700; background: transparent; }}
QLabel#mfSubtitle {{ color: #E0E7FF; font-size: 12.5px; background: transparent; }}

/* ---------- Body / kartu ---------- */
QScrollArea#mfScroll {{ background: transparent; border: none; }}
QScrollArea#mfScroll > QWidget > QWidget {{ background: transparent; }}
QWidget#mfBody {{ background: transparent; }}
QFrame#mfCard {{
    background: #FFFFFF;
    border: 1px solid #E6E8F0;
    border-radius: 12px;
}}
QFrame#mfCard QLabel {{ background: transparent; }}
QLabel#mfCardBadge {{
    background: #EDE9FE;
    border-radius: 9px;
    min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px;
    font-size: 17px;
}}
QLabel#mfCardTitle {{ color: #4C1D95; font-size: 14.5px; font-weight: 700; }}
QFrame#mfDivider {{ background: #EEF0F6; max-height: 1px; min-height: 1px; border: none; }}
QLabel#mfLabel {{ color: #4B5563; font-size: 12px; font-weight: 600; }}
QLabel#mfRequired {{ color: #DC2626; font-weight: 700; }}

/* ---------- Input ---------- */
QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{
    background: #FAFAFC;
    border: 1px solid #D9DCE6;
    border-radius: 8px;
    padding: 6px 11px;
    color: #111827;
    selection-background-color: #7C3AED;
    selection-color: #FFFFFF;
}}
QLineEdit:hover, QTextEdit:hover, QComboBox:hover, QSpinBox:hover,
QDoubleSpinBox:hover, QDateEdit:hover {{ border-color: #B4ABF2; }}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QDateEdit:focus {{ background: #FFFFFF; border: 1.5px solid #7C3AED; }}
QLineEdit[readOnly="true"] {{ background: #F1F2F6; color: #6B7280; border-color: #E5E7EB; }}
QLineEdit[invalid="true"], QTextEdit[invalid="true"], QComboBox[invalid="true"],
QSpinBox[invalid="true"], QDoubleSpinBox[invalid="true"], QDateEdit[invalid="true"] {{
    border: 1.5px solid #DC2626; background: #FEF2F2;
}}
QComboBox::drop-down, QDateEdit::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right;
    width: 30px; border: none;
}}
QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url({arrow}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: #FFFFFF; border: 1px solid #D9DCE6; padding: 4px; outline: 0;
    selection-background-color: #EDE9FE; selection-color: #4C1D95;
}}
QCheckBox {{ color: #374151; font-size: 12.5px; font-weight: 600; spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 20px; height: 20px; border-radius: 6px; border: 1.5px solid #C4C8D6; background: #FFFFFF; }}
QCheckBox::indicator:hover {{ border-color: #7C3AED; }}
QCheckBox::indicator:checked {{ background: #7C3AED; border-color: #7C3AED; }}

/* ---------- Scrollbar ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #C4B5FD; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #A78BFA; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

/* ---------- Footer ---------- */
QFrame#mfFooter {{ background: #FFFFFF; border-top: 1px solid #E6E8F0; }}
QLabel#mfHint {{ color: #6B7280; font-size: 12px; background: transparent; }}
QLabel#mfError {{
    background: #FEF2F2; color: #B91C1C; border: 1px solid #FECACA;
    border-radius: 8px; padding: 8px 12px; font-size: 12.5px;
}}
QPushButton#mfPrimary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7C3AED, stop:1 #4F46E5);
    color: #FFFFFF; border: none; border-radius: 8px;
    padding: 10px 30px; font-weight: 700; font-size: 13px;
}}
QPushButton#mfPrimary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6D28D9, stop:1 #4338CA);
}}
QPushButton#mfPrimary:pressed {{ background: #4C1D95; }}
QPushButton#mfSecondary {{
    background: #FFFFFF; color: #374151; border: 1px solid #D1D5DB;
    border-radius: 8px; padding: 10px 26px; font-weight: 600; font-size: 13px;
}}
QPushButton#mfSecondary:hover {{ background: #F3F4F6; }}
"""


class _WheelGuard(QObject):
    """Cegah combo/spinbox mengubah nilai saat user hanya men-scroll form."""

    def __init__(self, scroll: QScrollArea, parent: QObject | None = None):
        super().__init__(parent)
        self._scroll = scroll

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Wheel and isinstance(obj, QWidget) and not obj.hasFocus():
            bar = self._scroll.verticalScrollBar()
            bar.setValue(bar.value() - event.angleDelta().y() // 2)
            return True
        return False


class ModernFormDialog(FormDialog):
    """Form Tambah/Ubah bergaya kartu. Turunan FormDialog: membuat widget input,
    ekstraksi nilai, dan `collect()` memakai logika yang sama persis."""

    def __init__(
        self,
        title: str,
        fields: list[FieldSpec],
        initial: dict[str, Any] | None = None,
        parent: QWidget | None = None,
        maximized: bool = False,
        *,
        icon: str = "📝",
        subtitle: str = "",
        columns: int = 2,
        readonly_fields: tuple[str, ...] = (),
        send_empty_as_null: bool = False,
    ):
        # Sengaja TIDAK memanggil FormDialog.__init__ (layout lama) -- langsung
        # ke QDialog lalu set atribut yang dibutuhkan method warisan.
        QDialog.__init__(self, parent)
        self.setObjectName("modernForm")
        self.setWindowFlags(Qt.Dialog | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        # Minimize sengaja tidak ada (bug modal Qt, lihat catatan di FormDialog).
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowTitle(title)

        self.fields = fields
        self.initial = initial or {}
        self._inputs: dict[str, QWidget] = {}
        self._maximized = maximized
        self._icon = icon
        self._subtitle = subtitle
        self._columns = max(1, columns)
        self._readonly_fields = set(readonly_fields)
        self._send_empty_as_null = send_empty_as_null

        self.setStyleSheet(_build_qss())
        self._build_ui()
        self._apply_initial_size()

    # ------------------------------------------------------------------
    def _apply_initial_size(self) -> None:
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        width = 940 if self._columns >= 2 else 560
        height = 760
        if avail:
            width = min(width, int(avail.width() * 0.9))
            height = min(height, int(avail.height() * 0.9))
        self.setMinimumSize(min(640 if self._columns >= 2 else 460, width), 480)
        self.resize(width, height)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        self._scroll = QScrollArea()
        self._scroll.setObjectName("mfScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._wheel_guard = _WheelGuard(self._scroll, self)

        body = QWidget()
        body.setObjectName("mfBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 20, 24, 20)
        body_layout.setSpacing(16)
        for section_title, specs in self._group_by_section().items():
            body_layout.addWidget(self._build_card(section_title, specs))
        body_layout.addStretch()
        self._scroll.setWidget(body)
        root.addWidget(self._scroll, stretch=1)

        root.addWidget(self._build_footer())

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("mfHeader")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(28, 18, 28, 18)
        lay.setSpacing(16)

        icon = QLabel(self._icon)
        icon.setObjectName("mfIcon")
        icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(icon)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title = QLabel(self.windowTitle())
        title.setObjectName("mfTitle")
        text_col.addWidget(title)
        if self._subtitle:
            sub = QLabel(self._subtitle)
            sub.setObjectName("mfSubtitle")
            sub.setWordWrap(True)
            text_col.addWidget(sub)
        lay.addLayout(text_col, stretch=1)
        return header

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setObjectName("mfFooter")
        outer = QVBoxLayout(footer)
        outer.setContentsMargins(24, 12, 24, 14)
        outer.setSpacing(10)

        self._error_lbl = QLabel("")
        self._error_lbl.setObjectName("mfError")
        self._error_lbl.setWordWrap(True)
        self._error_lbl.hide()
        outer.addWidget(self._error_lbl)

        row = QHBoxLayout()
        row.setSpacing(10)
        hint = QLabel("<span style='color:#DC2626;font-weight:700'>*</span> wajib diisi")
        hint.setObjectName("mfHint")
        row.addWidget(hint)
        row.addStretch()

        cancel = QPushButton("Batal")
        cancel.setObjectName("mfSecondary")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)

        save = QPushButton("💾  Simpan")
        save.setObjectName("mfPrimary")
        save.setCursor(Qt.PointingHandCursor)
        save.setDefault(True)
        save.clicked.connect(self._on_accept)
        row.addWidget(save)
        outer.addLayout(row)
        return footer

    # ------------------------------------------------------------------
    def _build_card(self, title: str, specs: list[FieldSpec]) -> QFrame:
        card = QFrame()
        card.setObjectName("mfCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 18, 22, 20)
        lay.setSpacing(14)

        if title:
            head = QHBoxLayout()
            head.setSpacing(10)
            badge = QLabel(_SECTION_ICONS.get(title, "📄"))
            badge.setObjectName("mfCardBadge")
            badge.setAlignment(Qt.AlignCenter)
            head.addWidget(badge)
            lbl = QLabel(title)
            lbl.setObjectName("mfCardTitle")
            head.addWidget(lbl)
            head.addStretch()
            lay.addLayout(head)
            divider = QFrame()
            divider.setObjectName("mfDivider")
            lay.addWidget(divider)

        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(14)
        for c in range(self._columns):
            grid.setColumnStretch(c, 1)

        row = col = 0
        for spec in specs:
            cell = self._build_cell(spec)
            if spec.type == FieldType.TEXTAREA:
                if col != 0:
                    row += 1
                    col = 0
                grid.addWidget(cell, row, 0, 1, self._columns)
                row += 1
            else:
                grid.addWidget(cell, row, col)
                col += 1
                if col >= self._columns:
                    col = 0
                    row += 1
        lay.addLayout(grid)
        return card

    def _build_cell(self, spec: FieldSpec) -> QWidget:
        widget = self._create_input(spec)
        self._inputs[spec.name] = widget
        self._decorate(spec, widget)

        cell = QWidget()
        lay = QVBoxLayout(cell)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)

        if spec.type == FieldType.BOOL:
            assert isinstance(widget, QCheckBox)
            widget.setText(spec.label)
            lay.addSpacing(18)  # sejajar dengan input di sebelahnya
            lay.addWidget(widget)
            return cell

        label = QLabel(
            spec.label + (" <span style='color:#DC2626;font-weight:700'>*</span>" if spec.required else "")
        )
        label.setObjectName("mfLabel")
        label.setTextFormat(Qt.RichText)
        lay.addWidget(label)
        lay.addWidget(widget)
        return cell

    # ------------------------------------------------------------------
    def _decorate(self, spec: FieldSpec, widget: QWidget) -> None:
        """Poles widget bawaan FormDialog supaya cocok dengan tampilan kartu."""
        if isinstance(widget, QLineEdit):
            widget.setMinimumHeight(_INPUT_HEIGHT)
            if not widget.placeholderText():
                widget.setPlaceholderText(_PLACEHOLDERS.get(spec.name, ""))
            if spec.name in self._readonly_fields and self.initial.get(spec.name):
                widget.setReadOnly(True)
                widget.setToolTip("Kode tidak dapat diubah setelah dibuat.")
            widget.textChanged.connect(lambda *_a, w=widget: self._set_invalid(w, False))

        elif isinstance(widget, QTextEdit):
            widget.setMinimumHeight(84)
            widget.setMaximumHeight(120)
            widget.setFixedHeight(88)
            widget.setPlaceholderText(spec.help_text or _PLACEHOLDERS.get(spec.name, ""))
            widget.textChanged.connect(lambda w=widget: self._set_invalid(w, False))

        elif isinstance(widget, QComboBox):
            widget.setMinimumHeight(_INPUT_HEIGHT)
            widget.setFocusPolicy(Qt.StrongFocus)
            widget.installEventFilter(self._wheel_guard)
            if spec.type == FieldType.SELECT:
                current = widget.currentText()
                widget.setEditable(False)
                if current and widget.findText(current) < 0:
                    widget.addItem(current)
                widget.setCurrentIndex(max(0, widget.findText(current)))
            widget.currentIndexChanged.connect(lambda *_a, w=widget: self._set_invalid(w, False))

        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.setMinimumHeight(_INPUT_HEIGHT)
            widget.setButtonSymbols(QAbstractSpinBox.NoButtons)
            widget.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            widget.setFocusPolicy(Qt.StrongFocus)
            widget.installEventFilter(self._wheel_guard)
            if spec.name in _PREFIXES:
                widget.setPrefix(_PREFIXES[spec.name])
            if spec.name in _SUFFIXES:
                widget.setSuffix(_SUFFIXES[spec.name])

        elif isinstance(widget, QDateEdit):
            widget.setMinimumHeight(_INPUT_HEIGHT)
            widget.setFocusPolicy(Qt.StrongFocus)
            widget.installEventFilter(self._wheel_guard)

        elif isinstance(widget, QCheckBox):
            widget.setCursor(Qt.PointingHandCursor)

    @staticmethod
    def _set_invalid(widget: QWidget, invalid: bool) -> None:
        if bool(widget.property("invalid")) == invalid:
            return
        widget.setProperty("invalid", invalid)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _show_error(self, message: str) -> None:
        self._error_lbl.setText("⚠️  " + message)
        self._error_lbl.show()

    # ------------------------------------------------------------------
    def collect(self) -> tuple[dict[str, Any], str]:
        """Mode ubah (send_empty_as_null=True): kolom teks opsional yang DIKOSONGKAN
        user dikirim sebagai null supaya benar-benar terhapus di backend. Tanpa ini
        field kosong tidak ikut payload sehingga nilai lama tidak pernah hilang."""
        payload, error = super().collect()
        if error or not self._send_empty_as_null:
            return payload, error
        for spec in self.fields:
            if (
                spec.type in (FieldType.TEXT, FieldType.TEXTAREA)
                and not spec.required
                and spec.name not in self._readonly_fields
                and spec.name not in payload
            ):
                payload[spec.name] = None
        return payload, error

    def _on_accept(self) -> None:
        self._error_lbl.hide()
        missing: list[str] = []
        first_bad: QWidget | None = None
        for spec in self.fields:
            widget = self._inputs[spec.name]
            self._set_invalid(widget, False)
            if not spec.required:
                continue
            value = _extract_value(spec, widget)
            if value is None or value == "":
                self._set_invalid(widget, True)
                missing.append(spec.label)
                first_bad = first_bad or widget
        if missing:
            self._show_error("Lengkapi dulu kolom berikut: " + ", ".join(missing) + ".")
            if first_bad is not None:
                self._scroll.ensureWidgetVisible(first_bad, 0, 60)
                first_bad.setFocus()
            return

        payload, error = self.collect()
        if error:
            self._show_error(error)
            return
        self._payload = payload
        self.accept()


def modern_factory(
    *,
    icon: str = "📝",
    subtitle: str = "",
    columns: int = 2,
    readonly_fields: tuple[str, ...] = (),
    add_prefix: str = "Tambah",
    edit_prefix: str = "Ubah",
    entity: str = "Data",
) -> Callable[..., ModernFormDialog]:
    """Buat pabrik dialog dengan konfigurasi tetap; dipakai ChildRecordPanel.

    Signature hasil: factory(title, fields, initial=None, parent=None). Parameter
    `title` hanya dipakai kalau `entity` kosong; selain itu judul dibentuk dari
    `add_prefix`/`edit_prefix` + entity."""

    def _make(title: str, fields: list[FieldSpec], initial: dict[str, Any] | None = None,
              parent: QWidget | None = None) -> ModernFormDialog:
        if entity:
            title = f"{edit_prefix if initial else add_prefix} {entity}"
        sub = subtitle or ("Perbarui informasi di bawah ini." if initial else "Isi data di bawah ini.")
        return ModernFormDialog(
            title, fields, initial=initial, parent=parent,
            icon=icon, subtitle=sub, columns=columns, readonly_fields=readonly_fields,
            send_empty_as_null=bool(initial),
        )

    return _make
