"""
registry/module_registry.py
============================
Sumber kebenaran tunggal untuk SEMUA modul backend (35 router / 770
endpoint). Setiap entri `ModuleConfig` memetakan satu resource REST ke
layar generic CRUD (ui/pages/generic_module_page.py).

PENTING soal path: backend mendaftarkan setiap router dua kali ber-prefix
(prefix di app/main.py `_discover_and_register_adapter_routers` DITAMBAH
prefix bawaan APIRouter() di masing-masing file router). Contoh nyata:
    fastapi_ap_router.py -> APIRouter(prefix="/ap")
    didaftarkan dengan   -> app.include_router(router, prefix="/api/v1/ap")
    hasil akhir          -> /api/v1/ap/ap/invoices
Semua `base_path` di bawah ini SUDAH memperhitungkan duplikasi tsb sesuai
hasil inspeksi langsung terhadap source code backend.

Modul inti (Journal, COA, AR, AP, Ledger, Approvals, Dashboard, Capital,
Settings) mendapat layar KHUSUS (ui/pages/*) karena workflow-nya (double
entry, approval multi-level, laporan keuangan) tidak cocok direpresentasikan
sebagai grid generik. Modul tersebut TETAP terdaftar di sini untuk
referensi endpoint tapi ditandai `custom_page=True` sehingga navigasi
mengarah ke widget khusus, bukan grid generik.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FieldType(str, Enum):
    TEXT = "text"
    TEXTAREA = "textarea"
    NUMBER = "number"
    DECIMAL = "decimal"
    DATE = "date"
    DATETIME = "datetime"
    BOOL = "bool"
    SELECT = "select"
    UUID = "uuid"


@dataclass
class FieldSpec:
    name: str
    label: str = ""
    type: FieldType = FieldType.TEXT
    required: bool = False
    choices: tuple = ()
    default: object = None
    help_text: str = ""

    def __post_init__(self):
        if not self.label:
            self.label = self.name.replace("_", " ").strip().capitalize()


@dataclass
class ActionSpec:
    """Aksi workflow tambahan pada satu record, mis. approve/post/reverse."""
    name: str
    label: str
    method: str = "POST"
    path_suffix: str = ""  # ditambahkan setelah /{id}, mis "/approve"
    confirm: bool = True
    style: str = "default"  # default | primary | danger | success


@dataclass
class ModuleConfig:
    key: str
    label: str
    category: str
    icon: str
    base_path: str                       # path absolut setelah /api/v1
    list_path: str = ""                  # relatif ke base_path
    id_field: str = "id"
    columns: list = field(default_factory=list)     # [(field, label)]
    form_fields: list = field(default_factory=list)  # list[FieldSpec]
    actions: list = field(default_factory=list)      # list[ActionSpec]
    can_create: bool = True
    can_edit: bool = True
    can_delete: bool = True
    search_param: str = "search"
    custom_page: bool = False
    description: str = ""


STANDARD_DOC_ACTIONS = [
    ActionSpec("submit", "Submit", path_suffix="/submit", style="primary"),
    ActionSpec("approve", "Approve", path_suffix="/approve", style="success"),
    ActionSpec("reject", "Reject", path_suffix="/reject", style="danger"),
    ActionSpec("post", "Post", path_suffix="/post", style="primary"),
    ActionSpec("reverse", "Reverse", path_suffix="/reverse", style="danger"),
]

LOCK_ACTIONS = [
    ActionSpec("lock", "Lock", path_suffix="/lock"),
    ActionSpec("unlock", "Unlock", path_suffix="/unlock"),
]

ACTIVATE_ACTIONS = [
    ActionSpec("activate", "Activate", path_suffix="/activate", style="success"),
]

# ---------------------------------------------------------------------------
# REGISTRY
# ---------------------------------------------------------------------------
MODULES: dict[str, ModuleConfig] = {}


def _reg(cfg: ModuleConfig) -> None:
    MODULES[cfg.key] = cfg


# === Financial Core (custom pages, didaftarkan untuk referensi path) ======
_reg(ModuleConfig(
    key="journals", label="Jurnal Umum", category="Akuntansi Inti", icon="📒",
    base_path="/journals/journals", list_path="/", custom_page=True,
    description="Double-entry journal, draft-submit-approve-post-reverse.",
))
_reg(ModuleConfig(
    key="coa", label="Bagan Akun (COA)", category="Akuntansi Inti", icon="🌳",
    base_path="/coa/chart-of-accounts", list_path="/accounts", custom_page=True,
))
_reg(ModuleConfig(
    key="ledger", label="General Ledger & Laporan Keuangan", category="Akuntansi Inti", icon="📊",
    base_path="/ledger/ledger", custom_page=True,
))
_reg(ModuleConfig(
    key="ar", label="Piutang (AR)", category="Akuntansi Inti", icon="💰",
    base_path="/ar/ar", list_path="/invoices", custom_page=True,
))
_reg(ModuleConfig(
    key="ap", label="Utang (AP)", category="Akuntansi Inti", icon="💳",
    base_path="/ap/ap", list_path="/invoices", custom_page=True,
))
_reg(ModuleConfig(
    key="approvals", label="Approval Inbox", category="Akuntansi Inti", icon="✅",
    base_path="/approval/approvals", list_path="/my-tasks", custom_page=True,
))
_reg(ModuleConfig(
    key="fiscal_periods", label="Periode Fiskal", category="Akuntansi Inti", icon="🗓️",
    base_path="/fiscal-periods", list_path="/periods",
    columns=[("year", "Tahun"), ("month", "Bulan"), ("status", "Status")],
    form_fields=[
        FieldSpec("year", "Tahun", FieldType.NUMBER, required=True),
        FieldSpec("month", "Bulan", FieldType.NUMBER, required=True),
    ],
    actions=[
        ActionSpec("close", "Close Period", path_suffix="/close", style="danger"),
        ActionSpec("lock", "Lock Period", path_suffix="/lock"),
        ActionSpec("reopen", "Reopen Period", path_suffix="/reopen", style="primary"),
    ],
    can_delete=False,
))
_reg(ModuleConfig(
    key="capital", label="Modal & Dividen", category="Akuntansi Inti", icon="🏦",
    base_path="/capital", custom_page=True,
))

# === Master Data ============================================================
_reg(ModuleConfig(
    key="customers", label="Pelanggan (Customer)", category="Master Data", icon="🧑‍💼",
    base_path="/customers", list_path="/customers",
    columns=[("customer_code", "Kode"), ("name", "Nama"), ("city", "Kota"),
             ("credit_limit", "Limit Kredit"), ("is_active", "Aktif")],
    form_fields=[
        FieldSpec("customer_code", "Kode Customer", required=True),
        FieldSpec("name", "Nama", required=True),
        FieldSpec("npwp", "NPWP"),
        FieldSpec("address", "Alamat", FieldType.TEXTAREA),
        FieldSpec("city", "Kota"),
        FieldSpec("country", "Negara", default="Indonesia"),
        FieldSpec("phone", "Telepon"),
        FieldSpec("email", "Email"),
        FieldSpec("contact_person", "Contact Person"),
        FieldSpec("credit_limit", "Limit Kredit", FieldType.DECIMAL),
    ],
))
_reg(ModuleConfig(
    key="suppliers", label="Pemasok (Supplier)", category="Master Data", icon="🏭",
    base_path="/suppliers", list_path="/suppliers",
    columns=[("supplier_code", "Kode"), ("name", "Nama"), ("city", "Kota"),
             ("payment_terms_days", "Termin (hari)"), ("is_active", "Aktif")],
    form_fields=[
        FieldSpec("supplier_code", "Kode Supplier", required=True),
        FieldSpec("name", "Nama", required=True),
        FieldSpec("npwp", "NPWP"),
        FieldSpec("address", "Alamat", FieldType.TEXTAREA),
        FieldSpec("city", "Kota"),
        FieldSpec("country", "Negara", default="Indonesia"),
        FieldSpec("phone", "Telepon"),
        FieldSpec("email", "Email"),
        FieldSpec("contact_person", "Contact Person"),
        FieldSpec("payment_terms_days", "Termin Pembayaran (hari)", FieldType.NUMBER),
        FieldSpec("credit_limit", "Limit Kredit", FieldType.DECIMAL),
    ],
))
_reg(ModuleConfig(
    key="employees", label="Karyawan", category="Master Data", icon="👷",
    base_path="/employees", list_path="/employees",
    columns=[("employee_code", "Kode"), ("full_name", "Nama"), ("nik", "NIK"),
             ("basic_salary", "Gaji Pokok"), ("is_active", "Aktif")],
    form_fields=[
        FieldSpec("employee_code", "Kode Karyawan", required=True),
        FieldSpec("full_name", "Nama Lengkap", required=True),
        FieldSpec("npwp", "NPWP"),
        FieldSpec("nik", "NIK", required=True),
        FieldSpec("dependents", "Jumlah Tanggungan", FieldType.NUMBER, default=0),
        FieldSpec("basic_salary", "Gaji Pokok", FieldType.DECIMAL, required=True),
    ],
))
_reg(ModuleConfig(
    key="legal_entities", label="Entitas Legal", category="Master Data", icon="🏢",
    base_path="/legal-entities/legal-entities", list_path="/",
    columns=[("legal_name", "Nama Legal"), ("trade_name", "Nama Dagang"),
             ("entity_type", "Tipe"), ("npwp", "NPWP"), ("city", "Kota")],
    form_fields=[
        FieldSpec("legal_name", "Nama Legal", required=True),
        FieldSpec("trade_name", "Nama Dagang"),
        FieldSpec("entity_type", "Tipe Entitas", FieldType.SELECT,
                  choices=("PT", "CV", "UD", "Firma", "Koperasi", "Yayasan"), required=True),
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
    ],
))
_reg(ModuleConfig(
    key="iam_roles", label="Role & Permission", category="Master Data", icon="🔑",
    base_path="/iam/iam", list_path="/roles", custom_page=True,
    description="Manajemen role, permission, dan assignment role ke user.",
))
_reg(ModuleConfig(
    key="iam_users", label="Pengguna & Role", category="Master Data", icon="🔐",
    base_path="/iam/iam", list_path="/users",
    columns=[("username", "Username"), ("email", "Email"), ("full_name", "Nama"),
             ("department", "Departemen"), ("is_active", "Aktif"), ("is_locked", "Terkunci")],
    form_fields=[
        FieldSpec("username", "Username", required=True),
        FieldSpec("email", "Email", required=True),
        FieldSpec("full_name", "Nama Lengkap", required=True),
        FieldSpec("password", "Password", required=True),
        FieldSpec("department", "Departemen"),
        FieldSpec("job_title", "Jabatan"),
        FieldSpec("phone_number", "No. Telepon"),
        FieldSpec("must_change_password", "Wajib Ganti Password", FieldType.BOOL, default=True),
        FieldSpec("is_superuser", "Superuser", FieldType.BOOL, default=False),
        FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
    ],
    actions=[
        ActionSpec("lock", "Lock User", path_suffix="/lock", style="danger"),
        ActionSpec("unlock", "Unlock User", path_suffix="/unlock", style="success"),
        ActionSpec("reset-password", "Reset Password", path_suffix="/reset-password"),
    ],
))

# === Aktiva & Kas ============================================================
_reg(ModuleConfig(
    key="bank_accounts", label="Rekening Bank & Kas", category="Kas & Bank", icon="🏦",
    base_path="/bank-cash/bank-cash", list_path="/bank-accounts",
    columns=[("account_number", "No. Rekening"), ("account_name", "Nama Rekening"),
             ("bank_name", "Bank"), ("currency_code", "Mata Uang"), ("opening_balance", "Saldo Awal")],
    form_fields=[
        FieldSpec("account_number", "No. Rekening", required=True),
        FieldSpec("account_name", "Nama Rekening", required=True),
        FieldSpec("bank_name", "Nama Bank", required=True),
        FieldSpec("bank_code", "Kode Bank"),
        FieldSpec("currency_code", "Mata Uang", default="IDR", required=True),
        FieldSpec("account_type", "Tipe Akun", FieldType.SELECT,
                  choices=("checking", "savings", "cash", "petty_cash")),
        FieldSpec("opening_balance", "Saldo Awal", FieldType.DECIMAL, default=0),
        FieldSpec("opening_balance_date", "Tanggal Saldo Awal", FieldType.DATE),
    ],
    actions=ACTIVATE_ACTIONS + LOCK_ACTIONS,
))
_reg(ModuleConfig(
    key="bank_transactions", label="Transaksi Bank/Kas", category="Kas & Bank", icon="💵",
    base_path="/bank-cash/bank-cash", list_path="/transactions",
    columns=[("transaction_date", "Tanggal"), ("amount", "Jumlah"), ("description", "Keterangan")],
    form_fields=[
        FieldSpec("transaction_date", "Tanggal", FieldType.DATE, required=True),
        FieldSpec("amount", "Jumlah", FieldType.DECIMAL, required=True),
        FieldSpec("description", "Keterangan", FieldType.TEXTAREA, required=True),
    ],
))
_reg(ModuleConfig(
    key="fixed_assets", label="Aset Tetap", category="Aset", icon="🏗️",
    base_path="/fixed-assets/fixed-assets", list_path="/assets",
    columns=[("asset_code", "Kode"), ("asset_name", "Nama Aset"), ("asset_category", "Kategori"),
             ("acquisition_cost", "Harga Perolehan"), ("depreciation_method", "Metode Depresiasi")],
    form_fields=[
        FieldSpec("asset_code", "Kode Aset", required=True),
        FieldSpec("asset_name", "Nama Aset", required=True),
        FieldSpec("asset_category", "Kategori", required=True),
        FieldSpec("acquisition_date", "Tanggal Perolehan", FieldType.DATE, required=True),
        FieldSpec("acquisition_cost", "Harga Perolehan", FieldType.DECIMAL, required=True),
        FieldSpec("residual_value", "Nilai Residu", FieldType.DECIMAL, default=0),
        FieldSpec("useful_life_years", "Umur Manfaat (tahun)", FieldType.NUMBER, required=True),
        FieldSpec("depreciation_method", "Metode Depresiasi", FieldType.SELECT,
                  choices=("straight_line", "declining_balance", "units_of_production", "sum_of_years")),
        FieldSpec("depreciation_rate", "Tarif Depresiasi (%)", FieldType.DECIMAL),
        FieldSpec("location", "Lokasi"),
        FieldSpec("responsible_party", "Penanggung Jawab"),
        FieldSpec("serial_number", "No. Seri"),
    ],
    actions=[
        ActionSpec("run-depreciation", "Jalankan Depresiasi", path_suffix="/depreciate", style="primary"),
        ActionSpec("dispose", "Dispose Asset", path_suffix="/dispose", style="danger"),
    ],
))
_reg(ModuleConfig(
    key="intangible_assets", label="Aset Tak Berwujud", category="Aset", icon="💡",
    base_path="/intangible-assets/intangible-assets", list_path="/",
    columns=[("asset_code", "Kode"), ("asset_name", "Nama"), ("asset_category", "Kategori"),
             ("acquisition_cost", "Harga Perolehan"), ("amortization_method", "Metode Amortisasi")],
    form_fields=[
        FieldSpec("asset_code", "Kode Aset", required=True),
        FieldSpec("asset_name", "Nama Aset", required=True),
        FieldSpec("asset_category", "Kategori", required=True),
        FieldSpec("acquisition_date", "Tanggal Perolehan", FieldType.DATE, required=True),
        FieldSpec("acquisition_cost", "Harga Perolehan", FieldType.DECIMAL, required=True),
        FieldSpec("residual_value", "Nilai Residu", FieldType.DECIMAL, default=0),
        FieldSpec("useful_life_years", "Umur Manfaat (tahun)", FieldType.NUMBER, required=True),
        FieldSpec("amortization_method", "Metode Amortisasi", FieldType.SELECT,
                  choices=("straight_line", "declining_balance")),
        FieldSpec("registration_number", "No. Registrasi"),
        FieldSpec("issuing_authority", "Penerbit"),
        FieldSpec("expiry_date", "Tanggal Kadaluarsa", FieldType.DATE),
        FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
    ],
))
_reg(ModuleConfig(
    key="goodwill", label="Goodwill", category="Aset", icon="⭐",
    base_path="/goodwill/goodwill", list_path="/",
    columns=[("goodwill_code", "Kode"), ("goodwill_name", "Nama"),
             ("acquisition_cost", "Nilai Perolehan"), ("useful_life_years", "Umur Manfaat")],
    form_fields=[
        FieldSpec("goodwill_code", "Kode", required=True),
        FieldSpec("goodwill_name", "Nama", required=True),
        FieldSpec("goodwill_type", "Tipe"),
        FieldSpec("acquisition_date", "Tanggal Akuisisi", FieldType.DATE, required=True),
        FieldSpec("acquisition_cost", "Nilai Perolehan", FieldType.DECIMAL, required=True),
        FieldSpec("cash_generating_unit", "Cash Generating Unit"),
        FieldSpec("useful_life_years", "Umur Manfaat (tahun)", FieldType.NUMBER),
        FieldSpec("amortization_method", "Metode Amortisasi"),
        FieldSpec("description", "Deskripsi", FieldType.TEXTAREA),
    ],
    actions=[ActionSpec("impairment-test", "Uji Penurunan Nilai", path_suffix="/impairment-tests", style="primary")],
))
_reg(ModuleConfig(
    key="maintenance_assets", label="Aset Maintenance", category="Aset", icon="🔧",
    base_path="/maintenance/maintenance", list_path="/assets",
    columns=[("asset_code", "Kode"), ("asset_name", "Nama"), ("location", "Lokasi"), ("manufacturer", "Pabrikan")],
    form_fields=[
        FieldSpec("asset_code", "Kode Aset", required=True),
        FieldSpec("asset_name", "Nama Aset", required=True),
        FieldSpec("asset_category", "Kategori"),
        FieldSpec("location", "Lokasi"),
        FieldSpec("serial_number", "No. Seri"),
        FieldSpec("manufacturer", "Pabrikan"),
        FieldSpec("model", "Model"),
        FieldSpec("purchase_date", "Tanggal Pembelian", FieldType.DATE),
        FieldSpec("warranty_expiry_date", "Garansi s/d", FieldType.DATE),
        FieldSpec("maintenance_interval_days", "Interval Maintenance (hari)", FieldType.NUMBER),
    ],
))
_reg(ModuleConfig(
    key="maintenance_work_orders", label="Work Order Maintenance", category="Aset", icon="🛠️",
    base_path="/maintenance/maintenance", list_path="/work-orders",
    columns=[("work_order_number", "No. WO"), ("asset_id", "Aset"), ("status", "Status")],
    form_fields=[
        FieldSpec("asset_id", "Aset (UUID)", FieldType.UUID, required=True),
        FieldSpec("schedule_id", "Jadwal (UUID)", FieldType.UUID),
        FieldSpec("description", "Deskripsi", FieldType.TEXTAREA, required=True),
        FieldSpec("priority", "Prioritas", FieldType.SELECT, choices=("low", "medium", "high", "critical")),
    ],
    actions=STANDARD_DOC_ACTIONS[:3] + [ActionSpec("complete", "Complete", path_suffix="/complete", style="success")],
))

# === Inventory & Manufacturing ==============================================
_reg(ModuleConfig(
    key="inventory_items", label="Barang / Item", category="Inventori", icon="📦",
    base_path="/inventory/inventory", list_path="/items",
    columns=[("item_code", "Kode"), ("item_name", "Nama Barang"), ("category", "Kategori"),
             ("standard_cost", "HPP Standar"), ("selling_price", "Harga Jual")],
    form_fields=[
        FieldSpec("item_code", "Kode Barang", required=True),
        FieldSpec("item_name", "Nama Barang", required=True),
        FieldSpec("item_type", "Tipe", FieldType.SELECT, choices=("raw_material", "finished_good", "service", "trading")),
        FieldSpec("unit_of_measure", "Satuan", required=True),
        FieldSpec("category", "Kategori"),
        FieldSpec("brand", "Merek"),
        FieldSpec("reorder_point", "Titik Reorder", FieldType.NUMBER),
        FieldSpec("reorder_quantity", "Jumlah Reorder", FieldType.NUMBER),
        FieldSpec("standard_cost", "HPP Standar", FieldType.DECIMAL),
        FieldSpec("selling_price", "Harga Jual", FieldType.DECIMAL),
        FieldSpec("valuation_method", "Metode Valuasi", FieldType.SELECT, choices=("FIFO", "LIFO", "AVERAGE", "STANDARD")),
        FieldSpec("min_stock", "Stok Minimum", FieldType.NUMBER),
        FieldSpec("max_stock", "Stok Maksimum", FieldType.NUMBER),
        FieldSpec("description", "Deskripsi", FieldType.TEXTAREA),
    ],
))
_reg(ModuleConfig(
    key="stock_movements", label="Mutasi Stok", category="Inventori", icon="🔄",
    base_path="/inventory/inventory", list_path="/movements",
    columns=[("movement_date", "Tanggal"), ("movement_type", "Tipe"), ("quantity", "Qty"), ("unit_cost", "Harga Satuan")],
    form_fields=[
        FieldSpec("item_id", "Item (UUID)", FieldType.UUID, required=True),
        FieldSpec("movement_type", "Tipe Mutasi", FieldType.SELECT,
                  choices=("receipt", "issue", "transfer", "adjustment"), required=True),
        FieldSpec("quantity", "Qty", FieldType.DECIMAL, required=True),
        FieldSpec("unit_cost", "Harga Satuan", FieldType.DECIMAL),
        FieldSpec("movement_date", "Tanggal", FieldType.DATE, required=True),
        FieldSpec("warehouse_id", "Gudang (UUID)", FieldType.UUID),
        FieldSpec("to_warehouse_id", "Gudang Tujuan (UUID)", FieldType.UUID),
        FieldSpec("batch_number", "No. Batch"),
        FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
    ],
    can_edit=False,
))
_reg(ModuleConfig(
    key="warehouses", label="Gudang", category="Inventori", icon="🏬",
    base_path="/inventory/inventory", list_path="/warehouses",
    columns=[("warehouse_code", "Kode"), ("warehouse_name", "Nama"), ("location", "Lokasi")],
    form_fields=[
        FieldSpec("warehouse_code", "Kode Gudang", required=True),
        FieldSpec("warehouse_name", "Nama Gudang", required=True),
        FieldSpec("location", "Lokasi"),
    ],
))
_reg(ModuleConfig(
    key="bom", label="Bill of Materials", category="Manufaktur", icon="📐",
    base_path="/manufacturing/manufacturing", list_path="/bom",
    columns=[("bom_code", "Kode BOM"), ("bom_name", "Nama"), ("bom_version", "Versi"), ("is_default", "Default")],
    form_fields=[
        FieldSpec("bom_code", "Kode BOM", required=True),
        FieldSpec("bom_name", "Nama BOM", required=True),
        FieldSpec("product_id", "Produk (UUID)", FieldType.UUID, required=True),
        FieldSpec("bom_version", "Versi", default="1.0"),
        FieldSpec("effective_date", "Berlaku Sejak", FieldType.DATE, required=True),
        FieldSpec("expiry_date", "Berlaku Sampai", FieldType.DATE),
        FieldSpec("is_default", "Default", FieldType.BOOL, default=False),
        FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
    ],
))
_reg(ModuleConfig(
    key="routing", label="Routing Produksi", category="Manufaktur", icon="🧭",
    base_path="/manufacturing/manufacturing", list_path="/routing",
    columns=[("routing_code", "Kode"), ("routing_name", "Nama"), ("routing_version", "Versi")],
    form_fields=[
        FieldSpec("routing_code", "Kode Routing", required=True),
        FieldSpec("routing_name", "Nama Routing", required=True),
        FieldSpec("product_id", "Produk (UUID)", FieldType.UUID, required=True),
        FieldSpec("routing_version", "Versi", default="1.0"),
        FieldSpec("effective_date", "Berlaku Sejak", FieldType.DATE, required=True),
        FieldSpec("expiry_date", "Berlaku Sampai", FieldType.DATE),
        FieldSpec("is_default", "Default", FieldType.BOOL, default=False),
        FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
    ],
))
_reg(ModuleConfig(
    key="work_orders", label="Work Order Produksi", category="Manufaktur", icon="⚙️",
    base_path="/manufacturing/manufacturing", list_path="/work-orders",
    columns=[("wo_number", "No. WO"), ("product_id", "Produk"), ("quantity", "Qty"), ("status", "Status")],
    form_fields=[
        FieldSpec("bom_id", "BOM (UUID)", FieldType.UUID, required=True),
        FieldSpec("routing_id", "Routing (UUID)"),
        FieldSpec("quantity", "Qty Produksi", FieldType.DECIMAL, required=True),
        FieldSpec("planned_start_date", "Rencana Mulai", FieldType.DATE, required=True),
        FieldSpec("planned_end_date", "Rencana Selesai", FieldType.DATE),
        FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
    ],
    actions=STANDARD_DOC_ACTIONS[:3] + [ActionSpec("complete", "Complete", path_suffix="/complete", style="success")],
))

# === Purchase / Sales / Project =============================================
_reg(ModuleConfig(
    key="purchase_orders", label="Purchase Order", category="Pembelian & Penjualan", icon="🛒",
    base_path="/purchase-sales/purchase-sales", list_path="/purchase-orders",
    columns=[("po_number", "No. PO"), ("po_date", "Tanggal"), ("supplier_id", "Supplier"), ("status", "Status")],
    form_fields=[
        FieldSpec("po_number", "No. PO", required=True),
        FieldSpec("po_date", "Tanggal PO", FieldType.DATE, required=True),
        FieldSpec("supplier_id", "Supplier (UUID)", FieldType.UUID, required=True),
        FieldSpec("expected_delivery_date", "Estimasi Kirim", FieldType.DATE),
        FieldSpec("delivery_term_days", "Termin Kirim (hari)", FieldType.NUMBER),
        FieldSpec("payment_term_days", "Termin Bayar (hari)", FieldType.NUMBER),
        FieldSpec("incoterm", "Incoterm"),
        FieldSpec("order_type", "Tipe Order"),
        FieldSpec("reference_number", "No. Referensi"),
        FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
    ],
    actions=STANDARD_DOC_ACTIONS,
))
_reg(ModuleConfig(
    key="sales_orders", label="Sales Order", category="Pembelian & Penjualan", icon="🧾",
    base_path="/purchase-sales/purchase-sales", list_path="/sales-orders",
    columns=[("so_number", "No. SO"), ("so_date", "Tanggal"), ("customer_id", "Customer"), ("status", "Status")],
    form_fields=[
        FieldSpec("so_number", "No. SO", required=True),
        FieldSpec("so_date", "Tanggal SO", FieldType.DATE, required=True),
        FieldSpec("customer_id", "Customer (UUID)", FieldType.UUID, required=True),
        FieldSpec("expected_ship_date", "Estimasi Kirim", FieldType.DATE),
        FieldSpec("shipping_term_days", "Termin Kirim (hari)", FieldType.NUMBER),
        FieldSpec("payment_term_days", "Termin Bayar (hari)", FieldType.NUMBER),
        FieldSpec("incoterm", "Incoterm"),
        FieldSpec("order_type", "Tipe Order"),
        FieldSpec("reference_number", "No. Referensi"),
        FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
    ],
    actions=STANDARD_DOC_ACTIONS,
))
_reg(ModuleConfig(
    key="projects", label="Proyek & Jasa", category="Pembelian & Penjualan", icon="📁",
    base_path="/projects/projects", list_path="/",
    columns=[("project_code", "Kode"), ("project_name", "Nama Proyek"), ("contract_value", "Nilai Kontrak"), ("status", "Status")],
    form_fields=[
        FieldSpec("project_code", "Kode Proyek", required=True),
        FieldSpec("project_name", "Nama Proyek", required=True),
        FieldSpec("customer_id", "Customer (UUID)", FieldType.UUID),
        FieldSpec("start_date", "Tanggal Mulai", FieldType.DATE, required=True),
        FieldSpec("end_date", "Tanggal Selesai", FieldType.DATE),
        FieldSpec("contract_type", "Tipe Kontrak"),
        FieldSpec("contract_value", "Nilai Kontrak", FieldType.DECIMAL),
        FieldSpec("budget_total", "Total Budget", FieldType.DECIMAL),
        FieldSpec("revenue_recognition_method", "Metode Pengakuan Pendapatan",
                  FieldType.SELECT, choices=("percentage_of_completion", "completed_contract")),
        FieldSpec("billing_cycle_days", "Siklus Billing (hari)", FieldType.NUMBER),
        FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
    ],
))
_reg(ModuleConfig(
    key="time_entries", label="Timesheet", category="Pembelian & Penjualan", icon="⏱️",
    base_path="/projects/projects", list_path="/time-entries",
    columns=[("work_date", "Tanggal"), ("hours", "Jam"), ("is_billable", "Billable")],
    form_fields=[
        FieldSpec("project_id", "Proyek (UUID)", FieldType.UUID, required=True),
        FieldSpec("work_date", "Tanggal Kerja", FieldType.DATE, required=True),
        FieldSpec("hours", "Jam Kerja", FieldType.DECIMAL, required=True),
        FieldSpec("hourly_rate", "Tarif per Jam", FieldType.DECIMAL),
        FieldSpec("description", "Deskripsi", FieldType.TEXTAREA),
        FieldSpec("is_billable", "Billable", FieldType.BOOL, default=True),
        FieldSpec("task_code", "Kode Task"),
    ],
))

# === Treasury, Forex, Hedge, Consolidation ==================================
_reg(ModuleConfig(
    key="exchange_rates", label="Kurs Mata Uang", category="Treasury", icon="💱",
    base_path="/currency-exchange/currency-exchange", list_path="/rates",
    columns=[("from_currency", "Dari"), ("to_currency", "Ke"), ("rate", "Kurs"), ("effective_date", "Tanggal Berlaku")],
    form_fields=[
        FieldSpec("from_currency", "Dari Mata Uang", required=True),
        FieldSpec("to_currency", "Ke Mata Uang", required=True),
        FieldSpec("rate", "Kurs", FieldType.DECIMAL, required=True),
        FieldSpec("rate_type", "Tipe Kurs", FieldType.SELECT, choices=("spot", "middle", "buy", "sell", "kmk")),
        FieldSpec("effective_date", "Tanggal Berlaku", FieldType.DATE, required=True),
        FieldSpec("provider", "Sumber"),
        FieldSpec("bid_rate", "Bid Rate", FieldType.DECIMAL),
        FieldSpec("ask_rate", "Ask Rate", FieldType.DECIMAL),
    ],
    can_edit=False,
))
_reg(ModuleConfig(
    key="forex", label="Forex & Revaluasi", category="Treasury", icon="🌐",
    base_path="/forex/forex", list_path="/rates",
    columns=[("from_currency", "Dari"), ("to_currency", "Ke"), ("rate", "Kurs"), ("effective_date", "Tanggal")],
    form_fields=[
        FieldSpec("from_currency", "Dari Mata Uang", required=True),
        FieldSpec("to_currency", "Ke Mata Uang", required=True),
        FieldSpec("rate", "Kurs", FieldType.DECIMAL, required=True),
        FieldSpec("effective_date", "Tanggal Berlaku", FieldType.DATE, required=True),
    ],
    can_edit=False,
))
_reg(ModuleConfig(
    key="hedge_derivatives", label="Instrumen Derivatif", category="Treasury", icon="📈",
    base_path="/hedge/hedge", list_path="/derivatives",
    columns=[("instrument_code", "Kode"), ("derivative_type", "Tipe"), ("notional_amount", "Notional")],
    form_fields=[
        FieldSpec("instrument_code", "Kode Instrumen", required=True),
        FieldSpec("instrument_name", "Nama Instrumen", required=True),
        FieldSpec("derivative_type", "Tipe Derivatif", FieldType.SELECT,
                  choices=("forward", "option", "swap", "future")),
        FieldSpec("counterparty_id", "Counterparty (UUID)", FieldType.UUID),
        FieldSpec("underlying_asset", "Underlying Asset"),
        FieldSpec("notional_amount", "Notional Amount", FieldType.DECIMAL, required=True),
        FieldSpec("currency_code", "Mata Uang", required=True),
        FieldSpec("contract_date", "Tanggal Kontrak", FieldType.DATE, required=True),
        FieldSpec("settlement_date", "Tanggal Settlement", FieldType.DATE),
        FieldSpec("maturity_date", "Tanggal Jatuh Tempo", FieldType.DATE),
        FieldSpec("strike_price", "Strike Price", FieldType.DECIMAL),
        FieldSpec("premium_paid", "Premium Dibayar", FieldType.DECIMAL),
    ],
))
_reg(ModuleConfig(
    key="hedge_relationships", label="Hedge Relationship", category="Treasury", icon="🔗",
    base_path="/hedge/hedge", list_path="/relationships",
    columns=[("hedge_type", "Tipe"), ("hedged_item", "Item Dihedge"), ("hedge_ratio", "Rasio")],
    form_fields=[
        FieldSpec("hedge_type", "Tipe Hedge", FieldType.SELECT,
                  choices=("fair_value", "cash_flow", "net_investment")),
        FieldSpec("hedged_item", "Item Dihedge", required=True),
        FieldSpec("derivative_id", "Derivatif (UUID)", FieldType.UUID, required=True),
        FieldSpec("hedge_ratio", "Rasio Hedge", FieldType.DECIMAL, default=1),
        FieldSpec("designation_date", "Tanggal Penunjukan", FieldType.DATE, required=True),
        FieldSpec("effective_start_date", "Efektif Mulai", FieldType.DATE),
        FieldSpec("effective_end_date", "Efektif Sampai", FieldType.DATE),
        FieldSpec("risk_management_objective", "Tujuan Manajemen Risiko", FieldType.TEXTAREA),
    ],
))
_reg(ModuleConfig(
    key="consolidation_groups", label="Grup Konsolidasi", category="Treasury", icon="🧩",
    base_path="/consolidation/consolidation", list_path="/groups",
    columns=[("group_code", "Kode"), ("group_name", "Nama Grup"), ("functional_currency", "Mata Uang Fungsional")],
    form_fields=[
        FieldSpec("group_code", "Kode Grup", required=True),
        FieldSpec("group_name", "Nama Grup", required=True),
        FieldSpec("parent_entity_id", "Entitas Induk (UUID)", FieldType.UUID, required=True),
        FieldSpec("functional_currency", "Mata Uang Fungsional", default="IDR", required=True),
        FieldSpec("fiscal_year_start", "Awal Tahun Fiskal", FieldType.DATE),
        FieldSpec("description", "Deskripsi", FieldType.TEXTAREA),
    ],
))
_reg(ModuleConfig(
    key="intercompany", label="Transaksi Intercompany", category="Treasury", icon="🔀",
    base_path="/consolidation/consolidation", list_path="/intercompany",
    columns=[("transaction_date", "Tanggal"), ("amount", "Jumlah"), ("transaction_type", "Tipe")],
    form_fields=[
        FieldSpec("from_legal_entity_id", "Dari Entitas (UUID)", FieldType.UUID, required=True),
        FieldSpec("to_legal_entity_id", "Ke Entitas (UUID)", FieldType.UUID, required=True),
        FieldSpec("transaction_date", "Tanggal", FieldType.DATE, required=True),
        FieldSpec("amount", "Jumlah", FieldType.DECIMAL, required=True),
        FieldSpec("currency", "Mata Uang", default="IDR"),
        FieldSpec("exchange_rate", "Kurs", FieldType.DECIMAL, default=1),
        FieldSpec("transaction_type", "Tipe Transaksi"),
        FieldSpec("description", "Deskripsi", FieldType.TEXTAREA),
    ],
))

# === Payroll, Budget, Tax, Documents, Reports ==============================
_reg(ModuleConfig(
    key="payroll_runs", label="Payroll Run", category="SDM & Payroll", icon="🧮",
    base_path="/payroll", list_path="/runs",
    columns=[("period", "Periode"), ("status", "Status"), ("total_amount", "Total")],
    form_fields=[
        FieldSpec("period_year", "Tahun", FieldType.NUMBER, required=True),
        FieldSpec("period_month", "Bulan", FieldType.NUMBER, required=True),
        FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
    ],
    actions=STANDARD_DOC_ACTIONS[:3] + [ActionSpec("finalize", "Finalize", path_suffix="/finalize", style="success")],
))
_reg(ModuleConfig(
    key="budgets", label="Budget / Anggaran", category="Perencanaan", icon="📅",
    base_path="/budget/budget", list_path="/",
    columns=[("budget_code", "Kode"), ("budget_name", "Nama"), ("fiscal_year", "Tahun"), ("budget_type", "Tipe")],
    form_fields=[
        FieldSpec("budget_code", "Kode Budget", required=True),
        FieldSpec("budget_name", "Nama Budget", required=True),
        FieldSpec("budget_type", "Tipe Budget", FieldType.SELECT,
                  choices=("operational", "capital", "cash_flow", "master")),
        FieldSpec("fiscal_year", "Tahun Fiskal", FieldType.NUMBER, required=True),
        FieldSpec("period", "Periode", FieldType.SELECT, choices=("monthly", "quarterly", "annual")),
        FieldSpec("version", "Versi", default="1.0"),
        FieldSpec("effective_date", "Berlaku Sejak", FieldType.DATE, required=True),
        FieldSpec("expiry_date", "Berlaku Sampai", FieldType.DATE),
        FieldSpec("currency", "Mata Uang", default="IDR"),
        FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
    ],
    actions=STANDARD_DOC_ACTIONS[:3],
))
_reg(ModuleConfig(
    key="tax_faktur", label="Faktur Pajak (Coretax)", category="Pajak", icon="🧾",
    base_path="/tax/coretax/tax", list_path="/faktur-pajak",
    columns=[("reference_id", "No. Referensi"), ("faktur_date", "Tanggal"), ("nama_pembeli", "Pembeli"), ("dpp", "DPP")],
    form_fields=[
        FieldSpec("reference_id", "No. Referensi", required=True),
        FieldSpec("faktur_date", "Tanggal Faktur", FieldType.DATE, required=True),
        FieldSpec("npwp_pembeli", "NPWP Pembeli", required=True),
        FieldSpec("nama_pembeli", "Nama Pembeli", required=True),
        FieldSpec("alamat_pembeli", "Alamat Pembeli", FieldType.TEXTAREA),
        FieldSpec("dpp", "DPP", FieldType.DECIMAL, required=True),
        FieldSpec("ppn_rate", "Tarif PPN (%)", FieldType.DECIMAL, default=11),
        FieldSpec("is_ppn_bm", "PPnBM", FieldType.BOOL, default=False),
        FieldSpec("description", "Keterangan", FieldType.TEXTAREA),
    ],
))
_reg(ModuleConfig(
    key="documents", label="Manajemen Dokumen", category="Umum", icon="📎",
    base_path="/documents/documents", list_path="/",
    columns=[("filename", "Nama File"), ("document_type", "Tipe"), ("entity_type", "Terkait")],
    form_fields=[
        FieldSpec("entity_type", "Tipe Entitas Terkait"),
        FieldSpec("entity_id", "ID Entitas Terkait (UUID)", FieldType.UUID),
        FieldSpec("document_type", "Tipe Dokumen"),
        FieldSpec("description", "Deskripsi", FieldType.TEXTAREA),
    ],
    can_create=False,  # upload dilakukan lewat endpoint multipart terpisah
))
_reg(ModuleConfig(
    key="reports", label="Report Terjadwal", category="Umum", icon="🗂️",
    base_path="/reports/reports", list_path="/",
    columns=[("report_type", "Tipe Laporan"), ("schedule_name", "Nama Jadwal"), ("schedule_frequency", "Frekuensi")],
    form_fields=[
        FieldSpec("report_type", "Tipe Laporan", required=True),
        FieldSpec("schedule_name", "Nama Jadwal", required=True),
        FieldSpec("schedule_frequency", "Frekuensi", FieldType.SELECT,
                  choices=("daily", "weekly", "monthly", "quarterly")),
        FieldSpec("schedule_time", "Jam Jalan"),
        FieldSpec("report_format", "Format", FieldType.SELECT, choices=("pdf", "xlsx", "csv")),
        FieldSpec("is_active", "Aktif", FieldType.BOOL, default=True),
    ],
))
_reg(ModuleConfig(
    key="settings", label="Pengaturan Sistem", category="Umum", icon="⚙️",
    base_path="/settings/settings", custom_page=True,
))
_reg(ModuleConfig(
    key="audit", label="Audit & Forensik", category="Umum", icon="🕵️",
    base_path="/audit/audit", list_path="/findings",
    columns=[("finding_type", "Tipe Temuan"), ("severity", "Tingkat"), ("status", "Status")],
    can_create=False, can_edit=False, can_delete=False,
))
_reg(ModuleConfig(
    key="umkm", label="UMKM Simplified", category="Umum", icon="🏪",
    base_path="/umkm/umkm", list_path="/journals",
    columns=[("transaction_date", "Tanggal"), ("description", "Keterangan"), ("amount", "Jumlah")],
    form_fields=[
        FieldSpec("transaction_date", "Tanggal", FieldType.DATE, required=True),
        FieldSpec("description", "Keterangan", required=True),
        FieldSpec("amount", "Jumlah", FieldType.DECIMAL, required=True),
        FieldSpec("transaction_type", "Tipe", FieldType.SELECT, choices=("income", "expense")),
    ],
))
_reg(ModuleConfig(
    key="payments", label="Pembayaran (Umum)", category="Umum", icon="💸",
    base_path="/payments", list_path="/payments",
    columns=[("payment_number", "No. Pembayaran"), ("amount", "Jumlah"), ("reference_number", "Referensi")],
    form_fields=[
        FieldSpec("payment_number", "No. Pembayaran", required=True),
        FieldSpec("counterparty_id", "Counterparty (UUID)", FieldType.UUID, required=True),
        FieldSpec("amount", "Jumlah", FieldType.DECIMAL, required=True),
        FieldSpec("reference_number", "No. Referensi"),
        FieldSpec("description", "Keterangan", FieldType.TEXTAREA),
    ],
    actions=[
        ActionSpec("approve", "Approve", path_suffix="/approve", style="success"),
        ActionSpec("process", "Process", path_suffix="/process", style="primary"),
    ],
))


def get_module(key: str) -> ModuleConfig:
    return MODULES[key]


def modules_by_category() -> dict[str, list[ModuleConfig]]:
    out: dict[str, list[ModuleConfig]] = {}
    for cfg in MODULES.values():
        out.setdefault(cfg.category, []).append(cfg)
    return out


CATEGORY_ORDER = [
    "Akuntansi Inti",
    "Master Data",
    "Kas & Bank",
    "Aset",
    "Inventori",
    "Manufaktur",
    "Pembelian & Penjualan",
    "Treasury",
    "SDM & Payroll",
    "Perencanaan",
    "Pajak",
    "Umum",
]
