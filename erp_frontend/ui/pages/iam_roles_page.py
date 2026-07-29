"""
ui/pages/iam_roles_page.py
=============================
Manajemen Role & Permission (IAM) — bagian yang sebelumnya HILANG dari
frontend (halaman iam_users_page.py hanya kelola user, bukan role/
permission-nya). Tanpa halaman ini, role baru hanya bisa dibuat lewat
script/database langsung.

Endpoint backend (base: /iam/iam):
  GET/POST     /roles                          - daftar & buat role
  GET/PUT/DELETE /roles/{id}                    - detail/ubah/hapus role
  GET          /permissions?resource=...        - daftar semua permission
  POST         /roles/{id}/permissions          - assign banyak permission ke role
  DELETE       /roles/{id}/permissions/{pid}    - lepas 1 permission dari role
  GET/POST     /users/{id}/roles                - lihat/assign role ke user
  DELETE       /users/{id}/roles/{role_id}      - lepas role dari user

Catatan: RoleResponseSchema backend sudah menyertakan `permission_ids`
langsung di setiap role, jadi tidak perlu panggilan terpisah untuk
mengetahui permission apa saja yang dimiliki suatu role.

Halaman ini terdiri dari 2 tab:
  1. "Role & Permission"   - CRUD role + matrix checklist permission per role
  2. "Assign Role ke User" - pilih user, centang role yang dimiliki, simpan
"""
from __future__ import annotations

from typing import Any

from core.api_client import api_client
from core.formatting import extract_list
from core.workers import run_task
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

BASE = "/iam/iam"


class IamRolesPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)

        title = QLabel("🔑  Role & Permission (IAM)")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.role_tab = RolePermissionTab()
        self.assign_tab = AssignRoleToUserTab()
        self.tabs.addTab(self.role_tab, "Role & Permission")
        self.tabs.addTab(self.assign_tab, "Assign Role ke User")
        outer.addWidget(self.tabs, stretch=1)


# ==========================================================================
# TAB 1: Role list + permission checklist matrix
# ==========================================================================
class RolePermissionTab(QWidget):
    def __init__(self):
        super().__init__()
        self._roles: list[dict[str, Any]] = []
        self._all_permissions: list[dict[str, Any]] = []
        self._selected_role: dict[str, Any] | None = None
        self._checkboxes: dict[str, QCheckBox] = {}  # permission_id(str) -> checkbox
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)
        toolbar.addStretch()
        new_btn = QPushButton("+ Role Baru")
        new_btn.setObjectName("primaryButton")
        new_btn.clicked.connect(self._create_role)
        toolbar.addWidget(new_btn)
        edit_btn = QPushButton("✎ Ubah Role")
        edit_btn.clicked.connect(self._edit_role)
        toolbar.addWidget(edit_btn)
        delete_btn = QPushButton("🗑 Hapus Role")
        delete_btn.clicked.connect(self._delete_role)
        toolbar.addWidget(delete_btn)
        outer.addLayout(toolbar)

        splitter = QSplitter(Qt.Horizontal)

        # --- Kiri: daftar role ---
        self.role_table = QTableWidget(0, 4)
        self.role_table.setHorizontalHeaderLabels(["Nama Role", "Deskripsi", "Sistem", "Status"])
        self.role_table.horizontalHeader().setStretchLastSection(True)
        self.role_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.role_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.role_table.verticalHeader().setVisible(False)
        self.role_table.itemSelectionChanged.connect(self._on_role_selected)
        splitter.addWidget(self.role_table)

        # --- Kanan: matrix permission untuk role terpilih ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        self.perm_title = QLabel("Pilih role di sebelah kiri untuk mengatur permission-nya.")
        self.perm_title.setStyleSheet("font-weight:600;")
        self.perm_title.setWordWrap(True)
        right_layout.addWidget(self.perm_title)

        self.perm_scroll = QScrollArea()
        self.perm_scroll.setWidgetResizable(True)
        self.perm_container = QWidget()
        self.perm_layout = QVBoxLayout(self.perm_container)
        self.perm_layout.setAlignment(Qt.AlignTop)
        self.perm_scroll.setWidget(self.perm_container)
        right_layout.addWidget(self.perm_scroll, stretch=1)

        self.save_perm_btn = QPushButton("💾 Simpan Permission")
        self.save_perm_btn.setObjectName("primaryButton")
        self.save_perm_btn.setEnabled(False)
        self.save_perm_btn.clicked.connect(self._save_permissions)
        right_layout.addWidget(self.save_perm_btn)

        splitter.addWidget(right_panel)
        splitter.setSizes([480, 420])
        outer.addWidget(splitter, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self.status_label.setText("Memuat role & permission...")
        run_task(api_client.get, on_success=self._on_roles_loaded, on_error=self._on_error, path=f"{BASE}/roles")
        run_task(api_client.get, on_success=self._on_permissions_loaded, on_error=self._on_error,
                  path=f"{BASE}/permissions")

    def _on_roles_loaded(self, payload: Any) -> None:
        self._roles = extract_list(payload)
        self.role_table.setRowCount(len(self._roles))
        for row, role in enumerate(self._roles):
            values = [
                role.get("name", ""),
                role.get("description") or "-",
                "Ya" if role.get("is_system_role") else "Tidak",
                str(role.get("status", "")),
            ]
            for col, val in enumerate(values):
                self.role_table.setItem(row, col, QTableWidgetItem(val))
        self.role_table.resizeColumnsToContents()
        self.status_label.setText(f"{len(self._roles)} role dimuat.")

    def _on_permissions_loaded(self, payload: Any) -> None:
        self._all_permissions = extract_list(payload)
        if self._selected_role:
            self._render_permission_matrix()

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    # ------------------------------------------------------------------
    def _on_role_selected(self) -> None:
        row = self.role_table.currentRow()
        if row < 0 or row >= len(self._roles):
            self._selected_role = None
            self.save_perm_btn.setEnabled(False)
            return
        self._selected_role = self._roles[row]
        self.save_perm_btn.setEnabled(True)
        self._render_permission_matrix()

    def _render_permission_matrix(self) -> None:
        # bersihkan matrix lama
        while self.perm_layout.count():
            item = self.perm_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._checkboxes.clear()

        role = self._selected_role
        self.perm_title.setText(f"Permission untuk role: {role.get('name', '')}")

        current_ids = {str(pid) for pid in (role.get("permission_ids") or [])}

        # kelompokkan permission per resource supaya rapi
        grouped: dict[str, list[dict[str, Any]]] = {}
        for perm in self._all_permissions:
            grouped.setdefault(perm.get("resource", "other"), []).append(perm)

        for resource in sorted(grouped.keys()):
            group_label = QLabel(f"— {resource} —")
            group_label.setStyleSheet("font-weight:700; color:#374151; margin-top:8px;")
            self.perm_layout.addWidget(group_label)
            for perm in sorted(grouped[resource], key=lambda p: p.get("action", "")):
                pid = str(perm.get("id"))
                label = f"{perm.get('action', '')}  ({perm.get('name', '')})"
                if perm.get("description"):
                    label += f" — {perm['description']}"
                cb = QCheckBox(label)
                cb.setChecked(pid in current_ids)
                self._checkboxes[pid] = cb
                self.perm_layout.addWidget(cb)

    def _save_permissions(self) -> None:
        if not self._selected_role:
            return
        role_id = self._selected_role.get("id")
        current_ids = {str(pid) for pid in (self._selected_role.get("permission_ids") or [])}
        checked_ids = {pid for pid, cb in self._checkboxes.items() if cb.isChecked()}

        to_add = list(checked_ids - current_ids)
        to_remove = list(current_ids - checked_ids)

        if not to_add and not to_remove:
            QMessageBox.information(self, "Info", "Tidak ada perubahan permission.")
            return

        self.status_label.setText("Menyimpan perubahan permission...")
        self._pending_removals = to_remove
        self._pending_role_id = role_id

        if to_add:
            run_task(
                api_client.post,
                on_success=self._after_add_permissions,
                on_error=self._on_write_error,
                path=f"{BASE}/roles/{role_id}/permissions",
                json_body={"permission_ids": to_add},
            )
        else:
            self._after_add_permissions(None)

    def _after_add_permissions(self, _result: Any) -> None:
        if self._pending_removals:
            self._remove_next_permission()
        else:
            self._finish_save()

    def _remove_next_permission(self) -> None:
        if not self._pending_removals:
            self._finish_save()
            return
        perm_id = self._pending_removals.pop(0)
        run_task(
            api_client.delete,
            on_success=lambda _r: self._remove_next_permission(),
            on_error=self._on_write_error,
            path=f"{BASE}/roles/{self._pending_role_id}/permissions/{perm_id}",
        )

    def _finish_save(self) -> None:
        self.status_label.setText("Permission role berhasil disimpan.")
        self.refresh()

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal menyimpan.")

    # ------------------------------------------------------------------
    def _create_role(self) -> None:
        dlg = RoleFormDialog(parent=self)
        if dlg.exec():
            payload = dlg.build_payload()
            run_task(
                api_client.post,
                on_success=lambda _r: self._after_write("Role baru dibuat."),
                on_error=self._on_write_error,
                path=f"{BASE}/roles",
                json_body=payload,
            )

    def _edit_role(self) -> None:
        if not self._selected_role:
            QMessageBox.information(self, "Info", "Pilih role terlebih dahulu.")
            return
        dlg = RoleFormDialog(initial=self._selected_role, parent=self)
        if dlg.exec():
            payload = dlg.build_payload(is_update=True)
            role_id = self._selected_role.get("id")
            run_task(
                api_client.put,
                on_success=lambda _r: self._after_write("Role diperbarui."),
                on_error=self._on_write_error,
                path=f"{BASE}/roles/{role_id}",
                json_body=payload,
            )

    def _delete_role(self) -> None:
        if not self._selected_role:
            QMessageBox.information(self, "Info", "Pilih role terlebih dahulu.")
            return
        if self._selected_role.get("is_system_role"):
            QMessageBox.warning(self, "Tidak diizinkan", "Role sistem tidak bisa dihapus.")
            return
        confirm = QMessageBox.question(self, "Konfirmasi", f"Hapus role '{self._selected_role.get('name')}'?")
        if confirm != QMessageBox.Yes:
            return
        role_id = self._selected_role.get("id")
        run_task(
            api_client.delete,
            on_success=lambda _r: self._after_write("Role dihapus."),
            on_error=self._on_write_error,
            path=f"{BASE}/roles/{role_id}",
        )

    def _after_write(self, message: str) -> None:
        self.status_label.setText(message)
        self.refresh()


class RoleFormDialog(QDialog):
    def __init__(self, initial: dict[str, Any] | None = None, parent=None):
        super().__init__(parent)
        self.initial = initial or {}
        self.is_edit = bool(initial)
        self.setWindowTitle("Ubah Role" if self.is_edit else "Role Baru")
        self.resize(420, 260)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit(self.initial.get("name", ""))
        if self.is_edit:
            self.name_edit.setEnabled(False)  # nama role tidak bisa diubah (lihat RoleUpdateSchema)
        form.addRow("Nama Role", self.name_edit)

        self.desc_edit = QTextEdit(self.initial.get("description") or "")
        self.desc_edit.setFixedHeight(80)
        form.addRow("Deskripsi", self.desc_edit)

        self.system_check = QCheckBox("Role Sistem (tidak bisa dihapus)")
        self.system_check.setChecked(bool(self.initial.get("is_system_role", False)))
        if self.is_edit:
            self.system_check.setEnabled(False)
        form.addRow("", self.system_check)

        outer.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Simpan")
        buttons.button(QDialogButtonBox.Save).setObjectName("primaryButton")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _on_save(self) -> None:
        if not self.is_edit and len(self.name_edit.text().strip()) < 3:
            QMessageBox.warning(self, "Validasi", "Nama role minimal 3 karakter.")
            return
        self.accept()

    def build_payload(self, is_update: bool = False) -> dict[str, Any]:
        if is_update:
            return {"description": self.desc_edit.toPlainText().strip() or None}
        return {
            "name": self.name_edit.text().strip(),
            "description": self.desc_edit.toPlainText().strip() or None,
            "is_system_role": self.system_check.isChecked(),
        }


# ==========================================================================
# TAB 2: Assign role ke user tertentu
# ==========================================================================
class AssignRoleToUserTab(QWidget):
    def __init__(self):
        super().__init__()
        self._users: list[dict[str, Any]] = []
        self._roles: list[dict[str, Any]] = []
        self._selected_user: dict[str, Any] | None = None
        self._checkboxes: dict[str, QCheckBox] = {}
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel("Pilih User:"))
        self.user_combo = QComboBox()
        self.user_combo.setMinimumWidth(280)
        self.user_combo.currentIndexChanged.connect(self._on_user_changed)
        picker_row.addWidget(self.user_combo)
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self.refresh)
        picker_row.addWidget(refresh_btn)
        picker_row.addStretch()
        outer.addLayout(picker_row)

        self.role_list_label = QLabel("Pilih user untuk melihat role yang dimiliki.")
        self.role_list_label.setStyleSheet("font-weight:600; margin-top:8px;")
        outer.addWidget(self.role_list_label)

        self.role_checklist_container = QWidget()
        self.role_checklist_layout = QVBoxLayout(self.role_checklist_container)
        self.role_checklist_layout.setAlignment(Qt.AlignTop)
        outer.addWidget(self.role_checklist_container, stretch=1)

        save_btn = QPushButton("💾 Simpan Role User")
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self._save_user_roles)
        outer.addWidget(save_btn)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9CA3AF; font-size:11px;")
        outer.addWidget(self.status_label)

    def refresh(self) -> None:
        self.status_label.setText("Memuat user & role...")
        run_task(api_client.get, on_success=self._on_users_loaded, on_error=self._on_error,
                  path=f"{BASE}/users", params={"page_size": 200})
        run_task(api_client.get, on_success=self._on_roles_loaded, on_error=self._on_error, path=f"{BASE}/roles")

    def _on_users_loaded(self, payload: Any) -> None:
        self._users = extract_list(payload)
        self.user_combo.blockSignals(True)
        self.user_combo.clear()
        for u in self._users:
            self.user_combo.addItem(f"{u.get('username')} ({u.get('email', '')})", userData=u)
        self.user_combo.blockSignals(False)
        self.status_label.setText(f"{len(self._users)} user dimuat.")
        if self._users:
            self._on_user_changed(0)

    def _on_roles_loaded(self, payload: Any) -> None:
        self._roles = extract_list(payload)
        if self._selected_user:
            self._render_role_checklist()

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"Gagal memuat: {message}")

    def _on_user_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._users):
            return
        self._selected_user = self.user_combo.itemData(index)
        user_id = self._selected_user.get("id")
        run_task(api_client.get, on_success=self._on_user_roles_loaded, on_error=self._on_error,
                  path=f"{BASE}/users/{user_id}/roles")

    def _on_user_roles_loaded(self, payload: Any) -> None:
        user_roles = extract_list(payload)
        self._current_role_ids = {str(r.get("id")) for r in user_roles}
        self.role_list_label.setText(f"Role untuk user: {self._selected_user.get('username', '')}")
        self._render_role_checklist()

    def _render_role_checklist(self) -> None:
        while self.role_checklist_layout.count():
            item = self.role_checklist_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._checkboxes.clear()

        current_ids = getattr(self, "_current_role_ids", set())
        for role in self._roles:
            rid = str(role.get("id"))
            cb = QCheckBox(f"{role.get('name')} — {role.get('description') or ''}")
            cb.setChecked(rid in current_ids)
            self._checkboxes[rid] = cb
            self.role_checklist_layout.addWidget(cb)

    def _save_user_roles(self) -> None:
        if not self._selected_user:
            return
        user_id = self._selected_user.get("id")
        current_ids = getattr(self, "_current_role_ids", set())
        checked_ids = {rid for rid, cb in self._checkboxes.items() if cb.isChecked()}

        to_add = list(checked_ids - current_ids)
        to_remove = list(current_ids - checked_ids)

        if not to_add and not to_remove:
            QMessageBox.information(self, "Info", "Tidak ada perubahan role.")
            return

        self.status_label.setText("Menyimpan role user...")
        self._pending_removals = to_remove
        self._pending_user_id = user_id

        if to_add:
            run_task(
                api_client.post,
                on_success=lambda _r: self._remove_next_role(),
                on_error=self._on_write_error,
                path=f"{BASE}/users/{user_id}/roles",
                json_body={"role_ids": to_add},
            )
        else:
            self._remove_next_role()

    def _remove_next_role(self) -> None:
        if not self._pending_removals:
            self.status_label.setText("Role user berhasil disimpan.")
            self._on_user_changed(self.user_combo.currentIndex())
            return
        role_id = self._pending_removals.pop(0)
        run_task(
            api_client.delete,
            on_success=lambda _r: self._remove_next_role(),
            on_error=self._on_write_error,
            path=f"{BASE}/users/{self._pending_user_id}/roles/{role_id}",
        )

    def _on_write_error(self, message: str) -> None:
        QMessageBox.warning(self, "Gagal", message)
        self.status_label.setText("Gagal menyimpan.")
