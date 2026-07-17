# Sovereign ERP Desktop — Frontend PySide6

Frontend desktop **production-ready** untuk **Sovereign ERP Accounting Engine**
(backend FastAPI hexagonal-architecture, 35 modul / 770+ endpoint REST).
Client murni — semua logika bisnis, validasi, dan penyimpanan data ada di
backend; frontend ini hanya mengonsumsi REST API.

**Skala saat ini:** 65 modul UI (mencakup seluruh 35 router backend, dengan
beberapa router dipecah jadi beberapa modul UI karena punya banyak
sub-resource), ~16.500 baris kode, 83 file Python.

---

## 1. Instalasi

```bash
cd erp_frontend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Verifikasi Instalasi (Wajib Sebelum Deploy)

```bash
python smoke_test.py
```
Script ini menguji seluruh 65+ halaman bisa dibuat tanpa error Python/Qt
tanpa perlu koneksi ke backend. **Jalankan ini setiap kali update kode**
sebelum mendistribusikan ke user, supaya tidak ada regresi yang lolos.

Exit code `0` = semua lolos. Exit code `1` = ada error, jangan deploy.

## 3. Konfigurasi Server API

Default: `http://127.0.0.1:8000/api/v1`. Bisa diubah dengan:

1. Environment variable: `export ERP_API_BASE_URL="http://server:8000/api/v1"`
2. Kolom **Server** di layar login (tersimpan otomatis ke
   `~/.sovereign_erp/config.ini` setelah login pertama berhasil)

## 4. Menjalankan

```bash
python main.py
```

## 5. Build ke .exe (Windows, Distribusi ke User Akhir)

```bash
build_exe.bat
```
Atau manual:
```bash
pip install pyinstaller
pyinstaller SovereignERP.spec --noconfirm
```
Hasil ada di `dist/SovereignERP/SovereignERP.exe`. Copy seluruh folder
`dist/SovereignERP` untuk didistribusikan — tidak butuh Python terinstall
di komputer user.

---

## Logging & Debugging Produksi

Semua aktivitas (request API, error, exception tak tertangani) dicatat ke:
```
~/.sovereign_erp/logs/app.log      (rotating, max 5MB x 5 file)
```
Kalau user melapor bug, minta file ini — tidak perlu reproduce masalah
secara langsung. Exception fatal saat startup juga ditampilkan sebagai
dialog error yang jelas (bukan crash diam-diam).

## Ketahanan Jaringan (Retry Logic)

`core/api_client.py` otomatis retry request idempotent (GET/PUT/DELETE)
hingga 2x dengan backoff singkat jika terjadi error koneksi transient
(timeout, connection reset) — bukan error dari server (4xx/5xx tidak
di-retry karena mengulang tidak mengubah hasil).

---

## Arsitektur

```
erp_frontend/
├── main.py                      # entry point + logging setup + crash handler
├── smoke_test.py                # verifikasi instalasi sebelum deploy
├── SovereignERP.spec             # konfigurasi PyInstaller
├── build_exe.bat                 # script build 1-klik (Windows)
├── core/
│   ├── config.py                 # konfigurasi (base URL, timeout)
│   ├── session.py                 # state auth (token, user, legal entity)
│   ├── api_client.py              # REST client + auto refresh token + retry
│   ├── workers.py                  # QThreadPool wrapper agar UI non-blocking
│   ├── logging_setup.py            # rotating file log + crash handler
│   └── formatting.py               # helper format Rp, tanggal, status badge
├── registry/
│   └── module_registry.py          # sumber kebenaran 35 router: endpoint,
│                                     kolom tabel, field form
├── ui/
│   ├── theme.py                    # QSS global (tema profesional)
│   ├── login_window.py             # layar login (JWT + MFA)
│   ├── main_window.py              # shell: sidebar nav + topbar + stack
│   ├── widgets/                    # widget generik (tabel, form, KPI card)
│   └── pages/                      # 65+ halaman modul (lihat daftar di bawah)
```

### Mengapa "generic CRUD engine" + halaman khusus?

Backend punya 770+ endpoint di 35 modul. `GenericListPage` +
`registry/module_registry.py` menyediakan CRUD generik (tabel + form +
export) untuk modul-modul sederhana. Modul dengan workflow kompleks
(double-entry, approval multi-level, laporan keuangan, 3-way matching,
dsb) punya file halaman kustom sendiri di `ui/pages/`.

---

## Cakupan Modul (65 halaman UI / 35 router backend)

| Kategori | Jumlah Modul |
|---|---|
| Akuntansi Inti (Jurnal, COA, Ledger, AR, AP, Approval, dll) | 9 |
| Master Data (Customer, Supplier, Employee, IAM, dll) | 7 |
| Kas & Bank (Rekening, Transaksi, Rekonsiliasi, Transfer, Petty Cash) | 3 |
| Aset (Fixed Asset, Intangible, Goodwill, Maintenance) | 7 |
| Inventori (Item, Stok, Gudang, Stock Opname, Valuasi) | 4 |
| Manufaktur (BOM, Routing, WO, WIP, Cost Card) | 4 |
| Pembelian & Penjualan (PO, SO, Goods Receipt, Project) | 6 |
| Treasury (Forex, Hedge, Consolidation) | 10 |
| SDM & Payroll (Payroll Run, Salary Structure) | 2 |
| Perencanaan (Budget + Advanced) | 2 |
| Pajak (Faktur, SPT, e-Bupot) | 2 |
| Umum (Dokumen, Report, Settings, Audit, UMKM) | 9 |
| **TOTAL** | **65** |

## Fitur per Domain (Ringkasan)

- **Akuntansi**: Jurnal double-entry dengan validasi balance real-time,
  Bagan Akun (tree), Ledger lengkap (Trial Balance, Neraca, Laba-Rugi,
  Arus Kas, Perubahan Ekuitas, Rasio Keuangan, GL drill-down)
- **AR/AP**: Invoice, pembayaran, credit note, write-off, payment run,
  collection workflow, 3-way matching
- **Approval**: Inbox, Approval Matrix (konfigurasi level & delegasi)
- **IAM**: User, Role & Permission matrix, sesi login, MFA, riwayat login
- **Kas & Bank**: Rekonsiliasi, transfer, petty cash, import rekening koran
- **Inventory**: Item, mutasi, gudang, stock opname, kartu stok, valuasi
- **Aset**: Fixed/Intangible asset dengan jadwal depresiasi/amortisasi,
  Goodwill impairment test, Maintenance schedule
- **Manufacturing**: BOM, Routing, Work Order, WIP, Cost Card, Close HPP
- **Pajak**: Faktur Pajak, SPT Masa PPN/PPh21/PPh23, SPT Tahunan, e-Bupot,
  e-Meterai, NSFP
- **Payroll**: Payroll Run, Salary Structure & Component, Payslip
- **Treasury**: Forex/Currency Exchange (revaluasi, dashboard, posisi),
  Hedge (fair value IFRS 13, ineffectiveness), Consolidation (run,
  eliminasi, NCI)
- **Report**: Generate laporan ad-hoc (Financial/Ledger/Subledger/Tax/
  Analytics) dengan format PDF/Excel/CSV/HTML
- **Audit**: Hash-chain integrity, SOX control test, gap detection,
  audit trail

---

## Catatan Penting — Routing Path Backend

Backend mendaftarkan setiap router **dua kali ber-prefix** (prefix di
`app/main.py` DITAMBAH prefix bawaan `APIRouter()` masing-masing file
router), contoh: `fastapi_ap_router.py` di-mount di `/api/v1/ap` namun
router itu sendiri punya `prefix="/ap"`, sehingga path final adalah
`/api/v1/ap/ap/invoices`. Semua `base_path` di `registry/module_registry.py`
dan halaman kustom SUDAH memperhitungkan hal ini berdasarkan pemeriksaan
langsung terhadap source code backend.

Jika backend dijalankan via `asgi.py` (bukan `app.main:app`), verifikasi
dulu router mana saja yang terdaftar di sana — `asgi.py` versi awal hanya
mendaftarkan sebagian modul secara statis.

## Autentikasi

- `POST /iam/login` → `{username, password, mfa_code?, legal_entity_id?}`
- Access token (JWT) disertakan di header `Authorization: Bearer <token>`
- `legal_entity_id` ter-embed di JWT saat login
- Token di-refresh otomatis via `POST /iam/refresh` menjelang kadaluarsa

## Bootstrap Admin Pertama

Kalau database masih kosong, gunakan `create_first_admin.py` (taruh di
root folder backend, jalankan dengan venv backend aktif) untuk membuat
Legal Entity + Role Administrator (permission wildcard `*:*`) + User admin
pertama secara langsung ke database.

---

## Checklist Sebelum Go-Live

1. ☐ Jalankan `python smoke_test.py` — harus lolos 100%
2. ☐ Backend jalan via `uvicorn app.main:app` (bukan `asgi.py` parsial)
3. ☐ Login berhasil dengan user admin yang sudah dibuat
4. ☐ Uji minimal 1 alur transaksi penuh per modul kritis (Jurnal, AR, AP,
   Inventory) terhadap backend sungguhan
5. ☐ Cek `~/.sovereign_erp/logs/app.log` kosong dari error setelah smoke
   test manual di UI
6. ☐ Build .exe via `build_exe.bat` dan uji jalan di komputer lain tanpa
   Python terinstall
7. ☐ Set `ERP_API_BASE_URL` ke alamat server produksi (bukan localhost)

## Yang Masih Perlu Verifikasi Manual

Karena skala backend sangat besar (770+ endpoint), field/response JSON
untuk endpoint yang jarang dipakai sebaiknya diverifikasi terhadap server
sungguhan sebelum dipakai user akhir — terutama untuk modul yang field-nya
banyak diasumsikan dari nama variabel Pydantic (bukan hasil uji langsung
ke database berisi data).

Endpoint bulk export/import di 23 modul (audit, budget, coa, inventory,
journal, dll) memakai mekanisme export generik (tombol "Export" di
toolbar setiap `GenericListPage`) — belum ada UI dedicated untuk bulk
import (upload file massal).

## Lisensi Internal

Kode ini dibuat khusus untuk sistem ERP Anda dan tidak didistribusikan
ke pihak ketiga.
