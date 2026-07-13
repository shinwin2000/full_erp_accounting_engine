"""
ui/pages/legal_entities_page.py
==================================
Halaman modul "Entitas Legal" (Master Data).

Endpoint backend : /legal-entities/legal-entities/
Router asal      : lihat adapters/primary_api/v1/fastapi_*_router.py terkait

Kolom tabel, field form, dan aksi workflow modul ini didefinisikan LANGSUNG
di file ini (bukan dirujuk dari file lain) supaya isi file mencerminkan
struktur data modul backend secara langsung dan mudah dibaca/diaudit per
modul, tanpa perlu membuka file lain untuk memahami field apa saja yang
dipakai. Widget tabel + form generik (GenericListPage) tetap dipakai
bersama supaya perilaku CRUD & workflow-nya konsisten antar modul.
"""
from __future__ import annotations

from registry.module_registry import ActionSpec, FieldSpec, FieldType, ModuleConfig
from ui.widgets.generic_list_page import GenericListPage

# ---------------------------------------------------------------------------
# Kolom tabel daftar Entitas Legal
# ---------------------------------------------------------------------------
COLUMNS = [
    ("legal_name", "Nama Legal"),
    ("trade_name", "Nama Dagang"),
    ("entity_type", "Tipe"),
    ("npwp", "NPWP"),
    ("city", "Kota"),
]

# ---------------------------------------------------------------------------
# Field form tambah/ubah Entitas Legal
# ---------------------------------------------------------------------------
FORM_FIELDS = [
    FieldSpec("legal_name", "Nama Legal", required=True),
    FieldSpec("trade_name", "Nama Dagang"),
    FieldSpec("entity_type", "Tipe Entitas", FieldType.SELECT, required=True, choices=("PT", "CV", "UD", "Firma", "Koperasi", "Yayasan",)),
    FieldSpec("registration_number", "No. Registrasi"),
    FieldSpec("npwp", "NPWP"),
    FieldSpec("nppp", "NPPP"),
    FieldSpec("address", "Alamat", FieldType.TEXTAREA),
    FieldSpec("city", "Kota"),
    FieldSpec("postal_code", "Kode Pos"),
    FieldSpec("province", "Provinsi"),
    FieldSpec("country", "Negara", default="Indonesia"),
    FieldSpec("phone", "Telepon"),
    FieldSpec("email", "Email"),
    FieldSpec("website", "Website"),
]

# ---------------------------------------------------------------------------
# Aksi workflow tambahan (tombol di toolbar, POST /{id}/{aksi})
# ---------------------------------------------------------------------------
ACTIONS = []

CONFIG = ModuleConfig(
    key="legal_entities",
    label="Entitas Legal",
    category="Master Data",
    icon="🏢",
    base_path="/legal-entities/legal-entities",
    list_path="/",
    id_field="id",
    columns=COLUMNS,
    form_fields=FORM_FIELDS,
    actions=ACTIONS,
    can_create=True,
    can_edit=True,
    can_delete=True,
    search_param="search",
)


class LegalEntitiesPage(GenericListPage):
    """Halaman Entitas Legal."""

    def __init__(self, parent=None):
        super().__init__(CONFIG, parent)
