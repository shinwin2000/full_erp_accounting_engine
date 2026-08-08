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
    edit_http_method: str = "PUT"  # beberapa modul backend pakai PATCH, bukan PUT — lihat penjelasan di bawah
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
    key="approval_matrix", label="Approval Matrix & Delegasi", category="Akuntansi Inti", icon="🧭",
    base_path="/approval/approvals", custom_page=True,
    description="Konfigurasi aturan approval per level & delegasi wewenang.",
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
    edit_http_method="PATCH",
))
_reg(ModuleConfig(
    key="capital", label="Modal & Dividen", category="Akuntansi Inti", icon="🏦",
    base_path="/capital", custom_page=True,
))

# === Master Data ============================================================
# CUSTOMER - diambil dari versi pertama (lebih lengkap)
_reg(ModuleConfig(
    key="customers", label="Pelanggan (Customer)", category="Master Data", icon="🧑‍💼",
    base_path="/customers", list_path="/customers",
    # Kolom & field di bawah ini SENGAJA pakai nama persis sama dengan
    # CustomerResponseModel di fastapi_customer_router.py (customer_name,
    # tax_id, dst) supaya form Ubah ter-prefill benar dari data list, dan
    # payload create/update langsung cocok dengan request schema backend
    # (tidak ada lagi mismatch name<->customer_name / npwp<->tax_id).
    columns=[("customer_code", "Kode"), ("customer_name", "Nama"),
             ("company_name", "Perusahaan"), ("city", "Kota"), ("phone", "Telepon"),
             ("email", "Email"), ("credit_limit", "Limit Kredit"),
             ("current_balance", "Saldo Piutang"), ("status", "Status"),
             ("is_active", "Aktif"), ("created_at", "Dibuat")],
    form_fields=[
        FieldSpec("customer_code", "Kode Customer (kosongkan untuk auto: CUST-0001, dst)"),
        FieldSpec("customer_name", "Nama Customer", required=True),
        FieldSpec("company_name", "Nama Perusahaan"),
        FieldSpec("customer_type", "Tipe", FieldType.SELECT,
                  choices=("company", "individual", "government", "non_profit"),
                  default="company"),
        FieldSpec("tax_id", "NPWP"),
        FieldSpec("tax_status", "Status Pajak", FieldType.SELECT,
                  choices=("pkp", "non_pkp"), default="pkp"),
        FieldSpec("address", "Alamat", FieldType.TEXTAREA),
        FieldSpec("city", "Kota"),
        FieldSpec("province", "Provinsi"),
        FieldSpec("district", "Kecamatan"),
        FieldSpec("postal_code", "Kode Pos"),
        FieldSpec("country", "Negara (kode ISO 2 huruf)", default="ID"),
        FieldSpec("phone", "Telepon"),
        FieldSpec("mobile", "HP"),
        FieldSpec("email", "Email"),
        FieldSpec("website", "Website"),
        FieldSpec("contact_person", "Contact Person"),
        FieldSpec("contact_phone", "Telepon PIC"),
        FieldSpec("contact_email", "Email PIC"),
        FieldSpec("credit_limit", "Limit Kredit", FieldType.DECIMAL),
        FieldSpec("opening_balance", "Saldo Awal", FieldType.DECIMAL),
        FieldSpec("currency", "Mata Uang", default="IDR"),
        FieldSpec("payment_term_days", "Termin Pembayaran (hari)", FieldType.NUMBER, default=30),
        FieldSpec("discount_percent", "Diskon Default (%)", FieldType.DECIMAL),
        FieldSpec("category", "Kategori"),
        FieldSpec("price_group", "Price Level"),
    ],
    actions=[
        ActionSpec("activate", "Aktifkan", path_suffix="/activate", style="success"),
        ActionSpec("deactivate", "Nonaktifkan", path_suffix="/deactivate", style="danger"),
    ],
    edit_http_method="PATCH",
    description="Master Customer lengkap (identitas, pajak, alamat, finance, status). "
                 "Untuk alamat/PIC/attachment/notes/tags/riwayat kredit & saldo, buka "
                 "tombol '📋 Detail' pada baris terpilih.",
))

# SUPPLIER - diambil dari versi kedua (lebih lengkap)
_reg(ModuleConfig(
    key="suppliers", label="Pemasok (Supplier)", category="Master Data", icon="🏭",
    base_path="/suppliers", list_path="/suppliers",
    columns=[("supplier_code", "Kode"), ("name", "Nama Supplier"), ("company_name", "Perusahaan"),
             ("city", "Kota"), ("contact_person", "PIC"), ("phone", "Telepon"),
             ("payment_terms_days", "Termin (hari)"), ("credit_limit", "Limit Kredit"),
             ("status", "Status"), ("is_active", "Aktif")],
    form_fields=[
        # --- Informasi Umum ---
        FieldSpec("supplier_code", "Kode Supplier", required=True,
                  help_text="Kode unik supplier, mis. SUP-0001"),
        FieldSpec("name", "Nama Supplier", required=True),
        FieldSpec("company_name", "Nama Perusahaan"),
        FieldSpec("supplier_type", "Jenis Supplier", FieldType.SELECT,
                  choices=("individual", "company", "government", "non_profit"),
                  default="company",
                  help_text="individual=perorangan, company=perusahaan, government=pemerintah, non_profit=nirlaba"),
        FieldSpec("withholding_category", "Kategori PPh", FieldType.SELECT,
                  choices=("none", "pph23", "pph26", "both"), default="none"),
        # --- Pajak ---
        FieldSpec("npwp", "NPWP"),
        FieldSpec("tax_name", "Nama Wajib Pajak"),
        # --- Kontak ---
        FieldSpec("contact_person", "PIC (Contact Person)"),
        FieldSpec("email", "Email"),
        FieldSpec("phone", "Telepon"),
        FieldSpec("mobile", "HP"),
        FieldSpec("website", "Website"),
        # --- Alamat ---
        FieldSpec("address", "Alamat", FieldType.TEXTAREA),
        FieldSpec("city", "Kota"),
        FieldSpec("province", "Provinsi"),
        FieldSpec("postal_code", "Kode Pos"),
        FieldSpec("country", "Negara (kode ISO 2 huruf)", default="ID"),
        # --- Bank ---
        FieldSpec("bank_name", "Nama Bank"),
        FieldSpec("bank_account_number", "Nomor Rekening"),
        FieldSpec("bank_account_name", "Nama Pemilik Rekening"),
        # --- Keuangan ---
        FieldSpec("payment_terms_days", "Termin Pembayaran (hari)", FieldType.NUMBER, default=30),
        FieldSpec("credit_limit", "Limit Kredit", FieldType.DECIMAL, default=0),
        FieldSpec("opening_balance", "Saldo Awal", FieldType.DECIMAL, default=0),
        FieldSpec("opening_balance_date", "Tanggal Saldo Awal", FieldType.DATE),
        # --- Lainnya ---
        FieldSpec("status", "Status", FieldType.SELECT,
                  choices=("active", "inactive", "blocked", "suspended"), default="active"),
        FieldSpec("remarks", "Catatan", FieldType.TEXTAREA),
    ],
    actions=[
        ActionSpec("activate", "Aktifkan", path_suffix="/activate", style="success"),
        ActionSpec("deactivate", "Nonaktifkan", path_suffix="/deactivate", style="danger"),
    ],
    edit_http_method="PATCH",
))

# EMPLOYEE - sama di kedua versi (sederhana)
_reg(ModuleConfig(
    key="employees", label="Karyawan", category="Master Data", icon="👷",
    base_path="/employees", list_path="/employees",
    columns=[("employee_code", "Kode"), ("full_name", "Nama"), ("nik", "NIK"),
             ("basic_salary", "Gaji Pokok"), ("is_active", "Aktif")],
    form_fields=[
        FieldSpec("employee_code", "Kode Karyawan", required=True),
        FieldSpec("full_name", "Nama Lengkap", required=True),
        FieldSpec("npwp", "NPWP"),
        FieldSpec("nik", "NIK (KTP)"),
        FieldSpec("birth_date", "Tanggal Lahir", FieldType.DATE),
        FieldSpec("join_date", "Tanggal Bergabung", FieldType.DATE),
        FieldSpec("marital_status", "Status Pernikahan", FieldType.SELECT,
                  choices=("single", "married", "divorced", "widowed"), default="single"),
        FieldSpec("dependents", "Jumlah Tanggungan (PTKP)", FieldType.NUMBER, default=0),
        FieldSpec("basic_salary", "Gaji Pokok", FieldType.DECIMAL, default=0),
        FieldSpec("position_allowance", "Tunjangan Jabatan", FieldType.DECIMAL, default=0),
        FieldSpec("transport_allowance", "Tunjangan Transport", FieldType.DECIMAL, default=0),
        FieldSpec("meal_allowance", "Tunjangan Makan", FieldType.DECIMAL, default=0),
        FieldSpec("overtime_rate", "Tarif Lembur/Jam", FieldType.DECIMAL, default=0),
    ],
    edit_http_method="PATCH",
))

# LEGAL ENTITIES - sama di kedua versi
_reg(ModuleConfig(
    key="legal_entities", label="Entitas Legal", category="Master Data", icon="🏢",
    base_path="/legal-entities/legal-entities", list_path="/",
    columns=[("legal_name", "Nama Legal"), ("trade_name", "Nama Dagang"),
             ("entity_type", "Tipe"), ("npwp", "NPWP"), ("city", "Kota")],
    form_fields=[
        FieldSpec("legal_name", "Nama Legal (min. 3 karakter)", required=True),
        FieldSpec("trade_name", "Nama Dagang"),
        FieldSpec("entity_type", "Tipe Entitas", FieldType.SELECT,
                  choices=("corporation", "branch", "representative_office", "partnership",
                           "sole_proprietorship", "cooperative", "foundation", "consolidation_group"),
                  required=True,
                  help_text="corporation=PT, partnership=CV/Firma, sole_proprietorship=UD, cooperative=Koperasi, foundation=Yayasan"),
        FieldSpec("registration_number", "No. Registrasi (NIB)"),
        FieldSpec("npwp", "NPWP (harus 15 digit angka)", help_text="15 digit angka tanpa titik/strip"),
        FieldSpec("nppp", "NPPP (untuk PKP)"),
        FieldSpec("address", "Alamat", FieldType.TEXTAREA),
        FieldSpec("city", "Kota"),
        FieldSpec("postal_code", "Kode Pos"),
        FieldSpec("province", "Provinsi"),
        FieldSpec("country", "Negara (kode ISO 2 huruf)", default="ID"),
        FieldSpec("phone", "Telepon"),
        FieldSpec("email", "Email"),
        FieldSpec("website", "Website"),
        FieldSpec("fiscal_year_start", "Bulan Awal Tahun Fiskal (1-12)", FieldType.NUMBER, default=1),
        FieldSpec("fiscal_year_end", "Bulan Akhir Tahun Fiskal (1-12)", FieldType.NUMBER, default=12),
        FieldSpec("base_currency", "Mata Uang Dasar (3 huruf)", default="IDR"),
        FieldSpec("functional_currency", "Mata Uang Fungsional (3 huruf)", default="IDR"),
        FieldSpec("is_taxable", "PKP (Pengusaha Kena Pajak)", FieldType.BOOL, default=True),
        FieldSpec("is_withholding_agent", "Pemotong Pajak", FieldType.BOOL, default=True),
        FieldSpec("parent_company_id", "Perusahaan Induk (UUID, opsional)", FieldType.UUID),
    ],
))

# IAM modules - sama
_reg(ModuleConfig(
    key="iam_security", label="Keamanan Akun: Sesi, MFA & Password", category="Master Data", icon="🔐",
    base_path="/iam", custom_page=True,
    description="Manajemen sesi login, setup MFA, riwayat percobaan login, ganti password.",
))
_reg(ModuleConfig(
    key="iam_roles", label="Role & Permission", category="Master Data", icon="🔑",
    base_path="/iam", list_path="/roles", custom_page=True,
    description="Manajemen role, permission, dan assignment role ke user.",
))
_reg(ModuleConfig(
    key="iam_users", label="Pengguna & Role", category="Master Data", icon="🔐",
    base_path="/iam", list_path="/users",
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
# Semua modul di bawah ini sama di kedua versi, saya salin dari versi pertama (atau kedua, sama).
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
    key="bank_reconciliation", label="Rekonsiliasi & Transfer Bank", category="Kas & Bank", icon="🔄",
    base_path="/bank-cash/bank-cash", custom_page=True,
    description="Rekonsiliasi bank, transfer antar rekening, petty cash, cash book.",
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
    key="asset_lifecycle", label="Depresiasi, Amortisasi & Impairment", category="Aset", icon="🏗️",
    base_path="/fixed-assets/fixed-assets", custom_page=True,
    description="Jadwal depresiasi Aset Tetap, amortisasi Aset Tak Berwujud, uji impairment Goodwill.",
))
_reg(ModuleConfig(
    key="fixed_assets", label="Aset Tetap", category="Aset", icon="🏗️",
    base_path="/fixed-assets/fixed-assets", list_path="/assets",
    columns=[("asset_code", "Kode"), ("asset_name", "Nama Aset"), ("asset_category", "Kategori"),
             ("acquisition_cost", "Harga Perolehan"), ("depreciation_method", "Metode Depresiasi")],
    form_fields=[
        FieldSpec("asset_code", "Kode Aset", required=True),
        FieldSpec("asset_name", "Nama Aset", required=True),
        FieldSpec("asset_category", "Kategori", FieldType.SELECT,
                  choices=("building", "land", "machinery", "vehicle", "equipment", "furniture",
                           "computer", "software", "leasehold", "other"), required=True),
        FieldSpec("acquisition_date", "Tanggal Perolehan", FieldType.DATE, required=True),
        FieldSpec("acquisition_cost", "Harga Perolehan (harus > 0)", FieldType.DECIMAL, required=True),
        FieldSpec("residual_value", "Nilai Residu", FieldType.DECIMAL, default=0),
        FieldSpec("useful_life_years", "Umur Manfaat (tahun, harus > 0)", FieldType.NUMBER, required=True),
        FieldSpec("depreciation_method", "Metode Depresiasi", FieldType.SELECT,
                  choices=("straight_line", "declining_balance", "double_declining", "sum_of_years", "units_of_production"),
                  default="straight_line"),
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
        FieldSpec("asset_category", "Kategori", FieldType.SELECT,
                  choices=("patent", "trademark", "copyright", "software", "license", "franchise",
                           "goodwill", "customer_relationship"), required=True),
        FieldSpec("acquisition_date", "Tanggal Perolehan", FieldType.DATE, required=True),
        FieldSpec("acquisition_cost", "Harga Perolehan", FieldType.DECIMAL, required=True),
        FieldSpec("residual_value", "Nilai Residu", FieldType.DECIMAL, default=0),
        FieldSpec("useful_life_years", "Umur Manfaat (tahun)", FieldType.NUMBER, required=True),
        FieldSpec("amortization_method", "Metode Amortisasi", FieldType.SELECT,
                  choices=("straight_line", "declining_balance", "double_declining",
                           "sum_of_years", "units_of_production"), default="straight_line"),
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
        FieldSpec("goodwill_type", "Tipe", FieldType.SELECT,
                  choices=("purchase", "bargain", "internal", "consolidation"), default="purchase"),
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
    key="maintenance_schedule", label="Jadwal Maintenance & Spare Parts", category="Aset", icon="🔧",
    base_path="/maintenance/maintenance", custom_page=True,
    description="Jadwal maintenance preventif, pemakaian spare parts, ringkasan biaya.",
))
_reg(ModuleConfig(
    key="maintenance_assets", label="Aset Maintenance", category="Aset", icon="🔧",
    base_path="/maintenance/maintenance", list_path="/assets",
    columns=[("asset_code", "Kode"), ("asset_name", "Nama"), ("location", "Lokasi"), ("manufacturer", "Pabrikan")],
    form_fields=[
        FieldSpec("asset_code", "Kode Aset", required=True),
        FieldSpec("asset_name", "Nama Aset", required=True),
        FieldSpec("asset_category", "Kategori (min. karakter bebas)", required=True),
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
    columns=[("wo_number", "No. WO"), ("asset_id", "Aset"), ("maintenance_type", "Tipe"), ("status", "Status")],
    form_fields=[
        FieldSpec("wo_number", "No. Work Order", required=True),
        FieldSpec("asset_id", "Aset (UUID)", FieldType.UUID, required=True),
        FieldSpec("schedule_id", "Jadwal (UUID, opsional)", FieldType.UUID),
        FieldSpec("maintenance_type", "Tipe Maintenance", FieldType.SELECT,
                  choices=("preventive", "corrective", "predictive", "emergency", "routine"), required=True),
        FieldSpec("priority", "Prioritas", FieldType.SELECT,
                  choices=("low", "medium", "high", "critical"), default="medium"),
        FieldSpec("description", "Deskripsi", FieldType.TEXTAREA, required=True),
        FieldSpec("requested_by", "Diminta Oleh (UUID)", FieldType.UUID, required=True),
        FieldSpec("planned_start_date", "Rencana Mulai", FieldType.DATE, required=True),
        FieldSpec("planned_end_date", "Rencana Selesai (harus setelah mulai)", FieldType.DATE, required=True),
        FieldSpec("estimated_cost", "Estimasi Biaya", FieldType.DECIMAL, default=0),
        FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
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
        FieldSpec("item_code", "Kode Barang (min. 3 karakter)", required=True),
        FieldSpec("item_name", "Nama Barang (min. 3 karakter)", required=True),
        FieldSpec("item_type", "Tipe", FieldType.SELECT,
                  choices=("raw_material", "work_in_process", "finished_good", "trading", "consumable", "service"),
                  default="trading"),
        FieldSpec("unit_of_measure", "Satuan", default="pcs"),
        FieldSpec("category", "Kategori"),
        FieldSpec("brand", "Merek"),
        FieldSpec("reorder_point", "Titik Reorder", FieldType.DECIMAL, default=0),
        FieldSpec("reorder_quantity", "Jumlah Reorder", FieldType.DECIMAL, default=0),
        FieldSpec("standard_cost", "HPP Standar", FieldType.DECIMAL, default=0),
        FieldSpec("selling_price", "Harga Jual", FieldType.DECIMAL, default=0),
        FieldSpec("valuation_method", "Metode Valuasi", FieldType.SELECT,
                  choices=("FIFO", "LIFO", "AVERAGE", "STANDARD"), default="FIFO"),
        FieldSpec("warehouse_id", "Gudang Default (UUID, opsional)", FieldType.UUID),
        FieldSpec("min_stock", "Stok Minimum", FieldType.DECIMAL, default=0),
        FieldSpec("max_stock", "Stok Maksimum", FieldType.DECIMAL, default=0),
        FieldSpec("tax_rate_purchase", "Tarif Pajak Pembelian (%)", FieldType.DECIMAL, default=11),
        FieldSpec("tax_rate_sales", "Tarif Pajak Penjualan (%)", FieldType.DECIMAL, default=11),
        FieldSpec("is_lot_tracked", "Lacak per Batch/Lot", FieldType.BOOL, default=False),
        FieldSpec("is_serial_tracked", "Lacak per Serial Number", FieldType.BOOL, default=False),
        FieldSpec("is_expiry_tracked", "Lacak Tanggal Kadaluarsa", FieldType.BOOL, default=False),
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
                  choices=("IN", "OUT", "ADJUSTMENT", "TRANSFER_IN", "TRANSFER_OUT", "RETURN_IN", "RETURN_OUT", "SCRAP"),
                  required=True),
        FieldSpec("quantity", "Qty (harus > 0)", FieldType.DECIMAL, required=True),
        FieldSpec("unit_cost", "Harga Satuan", FieldType.DECIMAL),
        FieldSpec("movement_date", "Tanggal", FieldType.DATE, required=True),
        FieldSpec("reference_type", "Tipe Referensi", required=True,
                  help_text="mis. purchase_order, sales_order, production, adjustment"),
        FieldSpec("reference_id", "ID Referensi (UUID, opsional)", FieldType.UUID),
        FieldSpec("warehouse_id", "Gudang Asal (UUID)", FieldType.UUID, required=True),
        FieldSpec("to_warehouse_id", "Gudang Tujuan (UUID, wajib jika TRANSFER_IN/OUT)", FieldType.UUID),
        FieldSpec("batch_number", "No. Batch"),
        FieldSpec("serial_number", "No. Serial"),
        FieldSpec("expiry_date", "Tanggal Kadaluarsa", FieldType.DATE),
        FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
    ],
    can_edit=False,
))
_reg(ModuleConfig(
    key="stock_opname", label="Stock Opname & Valuasi", category="Inventori", icon="📋",
    base_path="/inventory/inventory", custom_page=True,
    description="Hitung fisik stok, kartu stok, valuasi persediaan, alert stok menipis.",
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
    key="manufacturing_advanced", label="WIP, Cost Card & Close HPP", category="Manufaktur", icon="⚙️",
    base_path="/manufacturing/manufacturing", custom_page=True,
    description="Work in Process, cost card produksi, analisis varians, close HPP bulanan.",
))
_reg(ModuleConfig(
    key="bom", label="Bill of Materials", category="Manufaktur", icon="📐",
    base_path="/manufacturing/manufacturing", custom_page=True,
    description="BOM dengan baris komponen (form generik tidak cukup krn butuh line items).",
))
_reg(ModuleConfig(
    key="routing", label="Routing Produksi", category="Manufaktur", icon="🧭",
    base_path="/manufacturing/manufacturing", custom_page=True,
    description="Routing dengan step produksi (form generik tidak cukup krn butuh line items).",
))
_reg(ModuleConfig(
    key="work_orders", label="Work Order Produksi", category="Manufaktur", icon="⚙️",
    base_path="/manufacturing/manufacturing", list_path="/work-orders",
    columns=[("work_order_number", "No. WO"), ("product_id", "Produk"), ("planned_quantity", "Qty"), ("status", "Status")],
    form_fields=[
        FieldSpec("work_order_number", "No. Work Order", required=True),
        FieldSpec("product_id", "Produk (UUID)", FieldType.UUID, required=True),
        FieldSpec("planned_quantity", "Qty Rencana (harus > 0)", FieldType.DECIMAL, required=True),
        FieldSpec("planned_start_date", "Rencana Mulai", FieldType.DATE, required=True),
        FieldSpec("planned_end_date", "Rencana Selesai", FieldType.DATE, required=True),
        FieldSpec("bom_id", "BOM (UUID, opsional)", FieldType.UUID),
        FieldSpec("routing_id", "Routing (UUID, opsional)", FieldType.UUID),
        FieldSpec("cost_center", "Cost Center"),
    ],
    actions=STANDARD_DOC_ACTIONS[:3] + [ActionSpec("complete", "Complete", path_suffix="/complete", style="success")],
))

# === Purchase / Sales / Project =============================================
_reg(ModuleConfig(
    key="goods_receipt", label="Goods Receipt & Delivery Order", category="Pembelian & Penjualan", icon="📥",
    base_path="/purchase-sales/purchase-sales", custom_page=True,
    description="Terima barang dari PO, kirim barang dari SO.",
))
_reg(ModuleConfig(
    key="purchase_orders", label="Purchase Order", category="Pembelian & Penjualan", icon="🛒",
    base_path="/purchase-sales/purchase-sales", custom_page=True,
    description="Purchase Order dengan baris item (form generik tidak cukup krn butuh line items).",
))
_reg(ModuleConfig(
    key="sales_orders", label="Sales Order", category="Pembelian & Penjualan", icon="🧾",
    base_path="/purchase-sales/purchase-sales", custom_page=True,
    description="Sales Order dengan baris item (form generik tidak cukup krn butuh line items).",
))
_reg(ModuleConfig(
    key="project_advanced", label="Retainer, Revenue Recognition & Dashboard", category="Pembelian & Penjualan", icon="📁",
    base_path="/projects/projects", custom_page=True,
    description="Retainer contract, pengakuan pendapatan PSAK 72, dashboard, utilisasi tim.",
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
        FieldSpec("contract_type", "Tipe Kontrak", FieldType.SELECT,
                  choices=("fixed_price", "time_material", "retainer", "cost_plus", "milestone")),
        FieldSpec("contract_value", "Nilai Kontrak", FieldType.DECIMAL),
        FieldSpec("budget_total", "Total Budget", FieldType.DECIMAL),
        FieldSpec("revenue_recognition_method", "Metode Pengakuan Pendapatan", FieldType.SELECT,
                  choices=("percentage_completion", "completed_contract", "straight_line",
                           "milestone", "input_method", "output_method")),
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
    key="currency_exchange_advanced", label="Currency Exchange: Revaluasi & Dashboard", category="Treasury", icon="💱",
    base_path="/currency-exchange/currency-exchange", custom_page=True,
    description="Master mata uang, revaluasi kurs, posisi, dashboard.",
))
_reg(ModuleConfig(
    key="exchange_rates", label="Kurs Mata Uang", category="Treasury", icon="💱",
    base_path="/currency-exchange/currency-exchange", list_path="/rates",
    columns=[("from_currency", "Dari"), ("to_currency", "Ke"), ("rate", "Kurs"), ("effective_date", "Tanggal Berlaku")],
    form_fields=[
        FieldSpec("from_currency", "Dari Mata Uang", required=True),
        FieldSpec("to_currency", "Ke Mata Uang", required=True),
        FieldSpec("rate", "Kurs", FieldType.DECIMAL, required=True),
        FieldSpec("rate_type", "Tipe Kurs", FieldType.SELECT,
                  choices=("mid", "buy", "sell", "spot", "forward", "swap"), default="mid"),
        FieldSpec("effective_date", "Tanggal Berlaku", FieldType.DATE, required=True),
        FieldSpec("provider", "Sumber"),
        FieldSpec("bid_rate", "Bid Rate", FieldType.DECIMAL),
        FieldSpec("ask_rate", "Ask Rate", FieldType.DECIMAL),
    ],
    can_edit=False,
))
_reg(ModuleConfig(
    key="forex_advanced", label="Forex: Revaluasi & Dashboard", category="Treasury", icon="🌐",
    base_path="/forex/forex", custom_page=True,
    description="Master mata uang, revaluasi kurs, posisi, dashboard (Forex).",
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
    key="hedge_advanced", label="Fair Value & Ketidakefektifan Hedge", category="Treasury", icon="📈",
    base_path="/hedge/hedge", custom_page=True,
    description="Pengukuran fair value (IFRS 13), ketidakefektifan hedge, dashboard.",
))
_reg(ModuleConfig(
    key="hedge_derivatives", label="Instrumen Derivatif", category="Treasury", icon="📈",
    base_path="/hedge/hedge", list_path="/derivatives",
    columns=[("instrument_code", "Kode"), ("derivative_type", "Tipe"), ("notional_amount", "Notional")],
    form_fields=[
        FieldSpec("instrument_code", "Kode Instrumen", required=True),
        FieldSpec("instrument_name", "Nama Instrumen", required=True),
        FieldSpec("derivative_type", "Tipe Derivatif", FieldType.SELECT,
                  choices=("forward", "futures", "option_call", "option_put", "swap_irs", "swap_ccs",
                           "swap_cds", "warrant", "structured")),
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
    key="consolidation_run", label="Jalankan Konsolidasi, Eliminasi & NCI", category="Treasury", icon="🧩",
    base_path="/consolidation/consolidation", custom_page=True,
    description="Eksekusi proses konsolidasi grup, eliminasi, dan perhitungan NCI.",
))
_reg(ModuleConfig(
    key="consolidation_groups", label="Grup Konsolidasi", category="Treasury", icon="🧩",
    base_path="/consolidation/consolidation", list_path="/groups",
    columns=[("group_code", "Kode"), ("group_name", "Nama Grup"), ("functional_currency", "Mata Uang Fungsional")],
    form_fields=[
        FieldSpec("group_code", "Kode Grup (min. 3 karakter)", required=True),
        FieldSpec("group_name", "Nama Grup (min. 3 karakter)", required=True),
        FieldSpec("parent_entity_id", "Entitas Induk (UUID, opsional)", FieldType.UUID),
        FieldSpec("functional_currency", "Mata Uang Fungsional (3 huruf)", default="IDR"),
        FieldSpec("fiscal_year_start", "Bulan Awal Tahun Fiskal (1-12)", FieldType.NUMBER, default=1),
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
        FieldSpec("transaction_type", "Tipe Transaksi", FieldType.SELECT,
                  choices=("sales", "service", "loan", "interest", "dividend", "fund_transfer"), required=True),
        FieldSpec("description", "Deskripsi", FieldType.TEXTAREA),
    ],
))

# === Payroll, Budget, Tax, Documents, Reports ==============================
_reg(ModuleConfig(
    key="payroll_salary", label="Struktur Gaji & Payslip", category="SDM & Payroll", icon="💰",
    base_path="/payroll", custom_page=True,
    description="Salary structure, salary components, payslip per karyawan.",
))
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
    key="budget_advanced", label="Budget Advanced", category="Perencanaan", icon="📅",
    base_path="/budget/budget", custom_page=True,
    description="Dashboard, alert, transfer anggaran, rolling forecast, versi, vs-actual.",
))
_reg(ModuleConfig(
    key="budgets", label="Budget / Anggaran", category="Perencanaan", icon="📅",
    base_path="/budget/budget", list_path="/",
    columns=[("budget_code", "Kode"), ("budget_name", "Nama"), ("fiscal_year", "Tahun"), ("budget_type", "Tipe")],
    form_fields=[
        FieldSpec("budget_code", "Kode Budget", required=True),
        FieldSpec("budget_name", "Nama Budget", required=True),
        FieldSpec("budget_type", "Tipe Budget", FieldType.SELECT,
                  choices=("operational", "capital", "cash", "project", "department", "fixed_asset", "sales")),
        FieldSpec("fiscal_year", "Tahun Fiskal", FieldType.NUMBER, required=True),
        FieldSpec("period", "Periode", FieldType.SELECT, choices=("monthly", "quarterly", "yearly")),
        FieldSpec("version", "Versi", default="1.0"),
        FieldSpec("effective_date", "Berlaku Sejak", FieldType.DATE, required=True),
        FieldSpec("expiry_date", "Berlaku Sampai", FieldType.DATE),
        FieldSpec("currency", "Mata Uang", default="IDR"),
        FieldSpec("notes", "Catatan", FieldType.TEXTAREA),
    ],
    actions=STANDARD_DOC_ACTIONS[:3],
))
_reg(ModuleConfig(
    key="tax_spt", label="SPT, e-Bupot & e-Meterai", category="Pajak", icon="🧾",
    base_path="/tax/coretax/tax", custom_page=True,
    description="SPT Masa PPN/PPh21/PPh23, SPT Tahunan Badan, e-Bupot, e-Meterai, NSFP.",
))
_reg(ModuleConfig(
    key="tax_faktur", label="Faktur Pajak (Coretax)", category="Pajak", icon="🧾",
    base_path="/tax/coretax/tax", list_path="/faktur-pajak",
    columns=[("reference_id", "No. Referensi"), ("faktur_date", "Tanggal"), ("nama_pembeli", "Pembeli"), ("dpp", "DPP")],
    form_fields=[
        FieldSpec("reference_id", "ID Referensi Invoice (UUID)", FieldType.UUID, required=True),
        FieldSpec("faktur_date", "Tanggal Faktur", FieldType.DATE, required=True),
        FieldSpec("npwp_pembeli", "NPWP Pembeli (15 digit angka)", required=True),
        FieldSpec("nama_pembeli", "Nama Pembeli", required=True),
        FieldSpec("alamat_pembeli", "Alamat Pembeli", FieldType.TEXTAREA),
        FieldSpec("dpp", "DPP (harus > 0)", FieldType.DECIMAL, required=True),
        FieldSpec("ppn_rate", "Tarif PPN (%)", FieldType.DECIMAL, default=11),
        FieldSpec("is_ppn_bm", "Kena PPnBM", FieldType.BOOL, default=False),
        FieldSpec("ppn_bm_rate", "Tarif PPnBM (%, jika kena PPnBM)", FieldType.DECIMAL, default=0),
        FieldSpec("note_type", "Tipe Faktur", FieldType.SELECT,
                  choices=("normal", "correction", "replacement"), default="normal"),
        FieldSpec("correction_sequence", "No. Urut Pembetulan (0 jika normal)", FieldType.NUMBER, default=0),
        FieldSpec("description", "Keterangan", FieldType.TEXTAREA),
    ],
))
_reg(ModuleConfig(
    key="documents", label="Manajemen Dokumen", category="Umum", icon="📎",
    base_path="/documents/documents", custom_page=True,
    description="Upload, download, dan workflow approval dokumen (implementasi lengkap).",
))
_reg(ModuleConfig(
    key="report_generation", label="Generate Laporan Ad-hoc", category="Umum", icon="🗂️",
    base_path="/reports/reports", custom_page=True,
    description="Generate laporan financial/ledger/subledger/tax/analytics on-demand.",
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
    key="audit_forensic", label="Audit Forensik & Kepatuhan", category="Umum", icon="🕵️",
    base_path="/audit/audit", custom_page=True,
    description="Hash-chain integrity, SOX control test, gap detection, laporan audit.",
))
_reg(ModuleConfig(
    key="audit", label="Audit & Forensik", category="Umum", icon="🕵️",
    base_path="/audit/audit", list_path="/findings",
    columns=[("finding_type", "Tipe Temuan"), ("severity", "Tingkat"), ("status", "Status")],
    can_create=False, can_edit=False, can_delete=False,
))
_reg(ModuleConfig(
    key="umkm_advanced", label="Profil, Akun & Kepatuhan Pajak UMKM", category="Umum", icon="🏪",
    base_path="/umkm/umkm", custom_page=True,
    description="Profil usaha, bagan akun sederhana, kepatuhan PPh Final, laporan sederhana.",
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
    columns=[("payment_number", "No. Pembayaran"), ("payment_type", "Tipe"), ("amount", "Jumlah"), ("payment_date", "Tanggal")],
    form_fields=[
        FieldSpec("payment_number", "No. Pembayaran", required=True),
        FieldSpec("payment_type", "Tipe Pembayaran", FieldType.SELECT, choices=("ap", "ar"), required=True,
                  help_text="ap = pembayaran ke supplier (utang), ar = penerimaan dari customer (piutang)"),
        FieldSpec("counterparty_id", "Counterparty (UUID)", FieldType.UUID, required=True),
        FieldSpec("amount", "Jumlah", FieldType.DECIMAL, required=True),
        FieldSpec("payment_date", "Tanggal Pembayaran", FieldType.DATE, required=True),
        FieldSpec("invoice_id", "Invoice Terkait (UUID, opsional)", FieldType.UUID),
        FieldSpec("reference_number", "No. Referensi"),
        FieldSpec("description", "Keterangan", FieldType.TEXTAREA),
    ],
    actions=[
        ActionSpec("approve", "Approve", path_suffix="/approve", style="success"),
        ActionSpec("process", "Process", path_suffix="/process", style="primary"),
    ],
    edit_http_method="PATCH",
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