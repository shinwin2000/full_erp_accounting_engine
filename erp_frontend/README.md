# Sovereign ERP Desktop — Frontend PySide6

Frontend desktop production-ready untuk **Sovereign ERP Accounting Engine**
(backend FastAPI hexagonal-architecture dengan 35 modul / 770+ endpoint REST).
Aplikasi ini adalah **client murni** — semua logika bisnis, validasi, dan
penyimpanan data tetap berada di backend; frontend hanya mengonsumsi REST API.

## 1. Instalasi

```bash
cd erp_frontend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Konfigurasi Server API

Default: `http://127.0.0.1:8000/api/v1`. Bisa diubah dengan salah satu cara:

1. Environment variable:
   ```bash
   export ERP_API_BASE_URL="http://alamat-server-anda:8000/api/v1"
   ```
2. Langsung di kolom **Server** pada layar login (tersimpan otomatis setelah
   login pertama kali berhasil, ke `~/.sovereign_erp/config.ini`).

## 3. Menjalankan

Pastikan backend (`full_erp_accounting_engine`) sudah berjalan terlebih
dahulu (mis. `uvicorn app.main:app --reload`), lalu:

```bash
python main.py
```

## 4. Build ke .exe / binary (opsional, PyInstaller)

```bash
pip install pyinstaller --break-system-packages
pyinstaller --noconfirm --windowed --name "SovereignERP" main.py
```
Hasil build ada di `dist/SovereignERP/`.

---

## Arsitektur

```
erp_frontend/
├── main.py                      # entry point, transisi Login <-> MainWindow
├── core/
│   ├── config.py                 # konfigurasi (base URL, timeout)
│   ├── session.py                 # state auth (token, user, legal entity)
│   ├── api_client.py              # REST client sinkron + auto refresh token
│   ├── workers.py                  # QThreadPool wrapper agar UI non-blocking
│   └── formatting.py               # helper format Rp, tanggal, status badge
├── registry/
│   └── module_registry.py          # SUMBER KEBENARAN 35 modul: endpoint,
│                                     kolom tabel, field form — inti dari
│                                     cakupan "semua modul"
├── ui/
│   ├── theme.py                    # QSS global (tema profesional)
│   ├── login_window.py             # layar login (JWT + MFA)
│   ├── main_window.py              # shell: sidebar nav + topbar + stack
│   ├── widgets/
│   │   ├── generic_table_model.py   # QAbstractTableModel generik
│   │   ├── generic_list_page.py     # ENGINE CRUD generik (dipakai 29 modul)
│   │   ├── form_dialog.py            # form auto-generate dari FieldSpec
│   │   └── kpi_card.py               # kartu KPI dashboard
│   └── pages/                       # layar KHUSUS untuk modul inti:
│       ├── dashboard_page.py
│       ├── coa_page.py               # Bagan Akun (tree view)
│       ├── journal_page.py           # Jurnal double-entry + workflow
│       ├── ledger_page.py            # Trial Balance/Neraca/Laba-Rugi/Cashflow
│       ├── invoice_workspace.py      # AR & AP (shared, party-parametrized)
│       ├── approvals_page.py         # Approval inbox multi-level
│       ├── capital_page.py           # Modal & dividen
│       └── settings_page.py          # Pengaturan sistem
```

### Mengapa "generic CRUD engine"?

Backend memiliki 770+ endpoint di 35 modul. Menulis layar unik untuk setiap
modul akan menghasilkan puluhan ribu baris kode yang sebagian besar
berulang (tabel + form + tombol CRUD). Sebagai gantinya, `GenericListPage`
+ `registry/module_registry.py` mendefinisikan **satu widget yang
dikonfigurasi**, sehingga menambah/mengubah modul cukup dengan menambah
entri di registry — tanpa menulis UI baru. ~29 dari 35 modul memakai
mekanisme ini (Customer, Supplier, Employee, Fixed Asset, Inventory,
Manufacturing, Purchase/Sales Order, Project, Forex, Hedge, Consolidation,
Payroll, Budget, Tax Coretax, Documents, Reports, Audit, UMKM, dst).

6 modul inti akuntansi (Journal, COA, Ledger, AR, AP, Approvals) plus
Capital & Settings mendapat **layar khusus** karena workflow-nya
(double-entry balance check, tree hierarki akun, laporan keuangan,
approval multi-level) tidak cocok direpresentasikan sebagai grid generik.

## Cakupan Modul (35 router backend)

| Kategori | Modul |
|---|---|
| Akuntansi Inti | Jurnal Umum, COA, General Ledger & Laporan Keuangan, AR, AP, Approval Inbox, Periode Fiskal, Modal & Dividen |
| Master Data | Customer, Supplier, Karyawan, Entitas Legal, User & Role (IAM) |
| Kas & Bank | Rekening Bank/Kas, Transaksi Bank/Kas |
| Aset | Aset Tetap, Aset Tak Berwujud, Goodwill, Aset Maintenance, Work Order Maintenance |
| Inventori | Barang/Item, Mutasi Stok, Gudang |
| Manufaktur | Bill of Materials, Routing, Work Order Produksi |
| Pembelian & Penjualan | Purchase Order, Sales Order, Proyek & Jasa, Timesheet |
| Treasury | Kurs Mata Uang, Forex & Revaluasi, Instrumen Derivatif, Hedge Relationship, Grup Konsolidasi, Intercompany |
| SDM & Payroll | Payroll Run |
| Perencanaan | Budget/Anggaran |
| Pajak | Faktur Pajak (Coretax) |
| Umum | Dokumen, Report Terjadwal, Pengaturan Sistem, Audit & Forensik, UMKM Simplified, Pembayaran |

## Catatan Penting — Routing Path Backend

Backend mendaftarkan setiap router **dua kali ber-prefix** (prefix di
`app/main.py` DITAMBAH prefix bawaan `APIRouter()` masing-masing file
router), contoh: `fastapi_ap_router.py` di-mount di `/api/v1/ap` namun
router itu sendiri punya `prefix="/ap"`, sehingga path final adalah
`/api/v1/ap/ap/invoices`. Semua `base_path` di `registry/module_registry.py`
SUDAH memperhitungkan hal ini berdasarkan pemeriksaan langsung terhadap
source code backend — tidak perlu diubah kecuali backend di-refactor.

## Autentikasi

- `POST /iam/login` → `{username, password, mfa_code?, legal_entity_id?}`
- Access token (JWT) disertakan di header `Authorization: Bearer <token>`
  pada semua request.
- `legal_entity_id` sudah ter-embed di dalam JWT saat login (dipilih dari
  daftar legal entity milik user), tidak perlu header tambahan.
- Token di-refresh otomatis via `POST /iam/refresh` ketika mendekati
  kadaluarsa (dilakukan transparan oleh `core/api_client.py`).

## Yang Perlu Diverifikasi Sebelum Go-Live

Aplikasi ini sudah disusun berdasarkan pemeriksaan langsung terhadap
seluruh source code backend (bukan tebakan), namun karena skala backend
sangat besar (770+ endpoint), disarankan untuk:

1. Menjalankan backend + frontend bersamaan dan uji tiap modul (checklist
   di bawah) — beberapa response JSON backend mungkin punya nama field
   yang sedikit berbeda dari asumsi (`extract_list()` di
   `core/formatting.py` sudah menangani beberapa variasi bentuk umum:
   `items`, `data`, `results`, list langsung).
2. Melengkapi field UUID (mis. `customer_id`, `project_id`) — saat ini
   diinput manual sebagai teks; untuk UX lebih baik, sambungkan ke
   autocomplete/picker yang memanggil endpoint pencarian terkait bila
   dibutuhkan.
3. Menyesuaikan daftar `choices` pada field `SELECT` (mis. status,
   kategori) dengan enum final yang dipakai backend di lingkungan Anda.

## Lisensi Internal

Kode ini dibuat khusus untuk sistem ERP Anda dan tidak didistribusikan
ke pihak ketiga.
