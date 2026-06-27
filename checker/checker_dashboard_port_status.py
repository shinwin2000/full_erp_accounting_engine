#!/usr/bin/env python3
"""
Dashboard Port Status — Monitoring implementasi port vs adapter.

Menampilkan:
- Status setiap port: REAL, PARTIAL, MISSING
- Semua metode yang hilang (untuk partial) — TIDAK DIPOTONG
- Adapter yang digunakan (untuk real/partial) dengan file path LENGKAP
- File port dan file adapter (lengkap dengan path relatif)
- REKOMENDASI file mana yang harus diedit untuk memperbaiki PARTIAL
- Ringkasan statistik
- Export ke JSON dan CSV
- DEBUG mode untuk melihat skor kandidat
"""

import ast
import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

# === Color ===
try:
    import colorama
    colorama.init(autoreset=True)
    RED = colorama.Fore.RED
    GREEN = colorama.Fore.GREEN
    YELLOW = colorama.Fore.YELLOW
    CYAN = colorama.Fore.CYAN
    MAGENTA = colorama.Fore.MAGENTA
    WHITE = colorama.Fore.WHITE
    BOLD = colorama.Style.BRIGHT
    RESET = colorama.Style.RESET_ALL
except ImportError:
    RED = GREEN = YELLOW = CYAN = MAGENTA = WHITE = BOLD = RESET = ""


def resolve_project_root() -> Path:
    """
    Secara dinamis melacak root folder proyek (E:\\full_erp_accounting_engine)
    berdasarkan keberadaan folder 'ports' dan 'adapters'.
    """
    curr = Path(__file__).resolve().parent
    for _ in range(5):  # Naik maksimal 5 tingkat ke atas
        if (curr / "ports").is_dir() and (curr / "adapters").is_dir():
            return curr
        curr = curr.parent
    return Path(__file__).resolve().parent.parent


ROOT = resolve_project_root()
EXCLUDE_PORTS = {"BasePort", "BaseRepository", "BaseProtocol", "Port", "Repository", "Protocol"}


@dataclass
class PortInfo:
    name: str
    module: str
    file: Path
    methods: set[str]
    abstract_methods: set[str]
    is_abstract: bool = False
    status: str = "MISSING"  # REAL, PARTIAL, MISSING
    adapter_class: str | None = None
    adapter_module: str | None = None
    adapter_file: Path | None = None
    missing_methods: set[str] = field(default_factory=set)
    file_to_edit: Path | None = None


@dataclass
class AdapterInfo:
    name: str
    module: str
    file: Path
    methods: set[str]
    bases: list[str]


# ============================================================================
# 1. SCAN PORTS (Hanya di folder ports/)
# ============================================================================

def get_all_ports() -> dict[str, PortInfo]:
    ports = {}
    ports_dir = ROOT / "ports"

    if not ports_dir.exists():
        print(f"{RED}[ERROR] Folder 'ports' tidak ditemukan di {ROOT}{RESET}")
        return ports

    for file_path in ports_dir.rglob("*.py"):
        if file_path.name == "__init__.py":
            continue

        rel_path = file_path.relative_to(ROOT)
        module_path = str(rel_path.with_suffix("")).replace("\\", ".").replace("/", ".")

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    name = node.name
                    if name in EXCLUDE_PORTS or name.startswith("_"):
                        continue

                    # Ketat: Hanya tangkap interface berakhiran Port / Protocol
                    if not any(name.endswith(s) for s in ("Port", "Protocol", "Interface")):
                        continue

                    methods = set()
                    abstract_methods = set()

                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            m_name = item.name
                            if m_name.startswith("_"):  # Abaikan private/dunder method
                                continue
                            methods.add(m_name)

                            is_abs = False
                            for dec in item.decorator_list:
                                dec_id = getattr(dec, "id", None) or getattr(getattr(dec, "func", None), "id", None)
                                dec_attr = getattr(dec, "attr", None)
                                if dec_id == "abstractmethod" or dec_attr == "abstractmethod":
                                    is_abs = True
                            if is_abs:
                                abstract_methods.add(m_name)

                    is_abc = any(
                        getattr(b, "id", "") in ("ABC", "Protocol") or getattr(b, "attr", "") in ("ABC", "Protocol")
                        for b in node.bases
                    )

                    ports[name] = PortInfo(
                        name=name,
                        module=module_path,
                        file=file_path,
                        methods=methods,
                        abstract_methods=abstract_methods,
                        is_abstract=(is_abc or bool(abstract_methods)),
                    )
        except Exception as e:
            print(f"{YELLOW}Gagal parsing AST {file_path}: {e}{RESET}")

    return ports


# ============================================================================
# 2. SCAN ADAPTERS (Di adapters/ dan infrastructure/)
# ============================================================================

def get_all_adapters() -> dict[str, AdapterInfo]:
    adapters = {}
    scan_targets = [ROOT / "adapters", ROOT / "infrastructure"]

    # Folder/File ORM murni yang dilarang dianggap sebagai adapter
    ignored_parts = {"persistence_orm", "migrations", "tests", "venv", ".git", "__pycache__"}

    for target_dir in scan_targets:
        if not target_dir.exists():
            continue

        for file_path in target_dir.rglob("*.py"):
            if file_path.name == "__init__.py" or file_path.name.endswith("_table.py"):
                continue

            if any(part in ignored_parts for part in file_path.parts):
                continue

            rel_path = file_path.relative_to(ROOT)
            module_path = str(rel_path.with_suffix("")).replace("\\", ".").replace("/", ".")

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(content)

                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        name = node.name
                        if any(k in name for k in ("Exception", "Error", "BaseModel", "Table")) or name.startswith("_"):
                            continue

                        methods = set()
                        for item in node.body:
                            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                if not item.name.startswith("_"):
                                    methods.add(item.name)

                        bases = []
                        for b in node.bases:
                            if isinstance(b, ast.Name):
                                bases.append(b.id)
                            elif isinstance(b, ast.Attribute):
                                bases.append(b.attr)

                        adapters[name] = AdapterInfo(
                            name=name,
                            module=module_path,
                            file=file_path,
                            methods=methods,
                            bases=bases
                        )
            except Exception:
                continue

    return adapters


# ============================================================================
# 3. MATCHING LOGIC (DIPERBAIKI)
# ============================================================================

KEYWORD_BOOST = {
    "BankAccountRepositoryPort": ["bank", "cash", "account"],
    "CashBookRepositoryPort": ["cash", "book", "bank"],
    "BankStatementImportPort": ["bank", "statement", "import"],
    "CustomerRepositoryPort": ["customer"],
    "SupplierRepositoryPort": ["supplier"],
    "EmployeeRepositoryPort": ["employee"],
    "InventoryRepositoryPort": ["inventory", "stock"],
    "FixedAssetRepositoryPort": ["fixed", "asset"],
    "PayrollRepositoryPort": ["payroll"],
    "ManufacturingRepositoryPort": ["manufacturing", "production"],
    "IAMUserRepositoryPort": ["iam", "user"],
    "IAMRepositoryPort": ["iam", "user"],
    "JournalRepositoryPort": ["journal"],
    "LedgerRepositoryPort": ["ledger"],
    "AccountRepositoryPort": ["account", "coa"],
    "ARRepositoryPort": ["ar", "receivable"],
    "APRepositoryPort": ["ap", "payable"],
    "TaxRepositoryPort": ["tax"],
    "BudgetRepositoryPort": ["budget"],
    "ForexRepositoryPort": ["forex", "exchange"],
    "HedgeRepositoryPort": ["hedge"],
    "ConsolidationRepositoryPort": ["consolidation"],
    "GoodwillRepositoryPort": ["goodwill"],
    "IntangibleAssetRepositoryPort": ["intangible"],
    "OutboxRepositoryPort": ["outbox"],
    "ApprovalRepositoryPort": ["approval"],
    "AMLRepositoryPort": ["aml", "anti_money"],
    "ProjectRepositoryPort": ["project"],
    "PurchaseOrderRepositoryPort": ["purchase", "order"],
    "SalesOrderRepositoryPort": ["sales", "order"],
    "WorkOrderRepositoryPort": ["work", "order"],
    "BillOfMaterialsRepositoryPort": ["bill", "materials", "bom"],
    "GoodsReceiptRepositoryPort": ["goods", "receipt"],
    "UMKMRepositoryPort": ["umkm"],
    "CachePort": ["cache", "redis"],
    "NotificationPort": ["notification", "email", "smtp"],
    "FileStoragePort": ["file", "storage", "s3"],
    "EncryptionKeyVaultPort": ["encryption", "vault"],
    "HashChainServicePort": ["hash", "chain"],
    "TimestampNotaryPort": ["timestamp", "notary"],
    "SagaStateStorePort": ["saga", "state"],
    "SnapshotStorePort": ["snapshot"],
    "ReadModelProjectionPort": ["read", "model", "projection"],
    "CQRSQueryHandlerPort": ["cqrs", "query"],
    "AnalyticsExportPort": ["analytics", "export"],
    "ReportRepositoryPort": ["report"],
    "CoreTaxPort": ["coretax", "tax", "core"],
    "TaxAuthorityCoretaxPort": ["coretax", "tax", "authority"],
    "TaxTransactionRepositoryPort": ["tax", "transaction"],
}


def match_port_to_adapter(
    port: PortInfo,
    adapters: dict[str, AdapterInfo],
    debug: bool = False
) -> tuple[str | None, str | None, set[str], Path | None]:
    """
    Mencari adapter terbaik untuk port tertentu dengan skoring yang lebih cerdas.
    """
    port_stem = port.name
    for suffix in ("Port", "Protocol", "Interface"):
        if port_stem.endswith(suffix):
            port_stem = port_stem[:-len(suffix)]
            break

    required_methods = port.abstract_methods if (port.is_abstract and port.abstract_methods) else port.methods

    candidates = []
    for adp_name, adp in adapters.items():
        score = 0

        # 1. Explicit inheritance (poin tertinggi, tapi beri penalti jika multi-bases)
        if port.name in adp.bases:
            score += 1000
            # Penalti jika adapter mewarisi banyak port (indikasi multipurpose)
            other_ports = [b for b in adp.bases if b.endswith(('Port', 'Protocol', 'Interface')) and b != port.name]
            if other_ports:
                score -= len(other_ports) * 200  # Penalti berat

        # 2. Kecocokan nama (spesifisitas)
        # Hitung seberapa mirip stem port dengan nama adapter
        adp_lower = adp_name.lower()
        if port_stem.lower() in adp_lower:
            # Bonus lebih besar jika stem berada di awal atau sebagai kata utuh
            if adp_lower.startswith(port_stem.lower()):
                score += 500
            else:
                score += 300
        elif port.name.lower() in adp_lower:
            score += 200

        # 3. Method overlap
        overlap = required_methods.intersection(adp.methods)
        missing = required_methods.difference(adp.methods)
        # Beri poin proporsional: jika method lengkap, skor tinggi
        if required_methods:
            coverage = len(overlap) / len(required_methods)
            score += coverage * 200  # Maksimal +200
        else:
            # Marker interface tanpa method
            score += 100

        # 4. Keyword booster
        if port.name in KEYWORD_BOOST:
            for kw in KEYWORD_BOOST[port.name]:
                if kw in adp_name.lower() or kw in adp.file.stem.lower():
                    score += 50
                    break

        # 5. Penalti jika adapter mewarisi port lain yang sama sekali tidak terkait
        # (ini sudah tercakup di poin 1)

        # Simpan kandidat
        candidates.append((adp_name, adp, score, missing))

    # Urutkan berdasarkan skor tertinggi
    candidates.sort(key=lambda x: x[2], reverse=True)

    if debug:
        print(f"\n{CYAN}DEBUG: Port {port.name} candidates:{RESET}")
        for i, (name, adp, score, missing) in enumerate(candidates[:5]):
            print(f"  {i+1}. {name} (score={score}, missing={len(missing)})")

    # Pilih yang terbaik jika skor >= 100
    if candidates and candidates[0][2] >= 100:
        best_name, best_adp, _, best_missing = candidates[0]
        return best_name, best_adp.module, best_missing, best_adp.file

    return None, None, set(), None


# ============================================================================
# 4. GENERATE & PRINT
# ============================================================================

def generate_dashboard(debug: bool = False) -> tuple[list[PortInfo], dict[str, int]]:
    ports = get_all_ports()
    adapters = get_all_adapters()

    status_counts = {"REAL": 0, "PARTIAL": 0, "MISSING": 0}

    for port_info in ports.values():
        adapter_name, adapter_module, missing, adapter_file = match_port_to_adapter(port_info, adapters, debug)

        if adapter_name and not missing:
            port_info.status = "REAL"
            status_counts["REAL"] += 1
            port_info.adapter_class = adapter_name
            port_info.adapter_module = adapter_module
            port_info.adapter_file = adapter_file
            port_info.missing_methods = set()
        elif adapter_name and missing:
            port_info.status = "PARTIAL"
            status_counts["PARTIAL"] += 1
            port_info.adapter_class = adapter_name
            port_info.adapter_module = adapter_module
            port_info.adapter_file = adapter_file
            port_info.missing_methods = missing
            port_info.file_to_edit = adapter_file
        else:
            port_info.status = "MISSING"
            status_counts["MISSING"] += 1

    return list(ports.values()), status_counts


def print_dashboard(ports: list[PortInfo], status_counts: dict[str, int]):
    print(f"\n{BOLD}{CYAN}====================================================================")
    print("               PORT & ADAPTER IMPLEMENTATION DASHBOARD              ")
    print(f"===================================================================={RESET}")
    print(f"{WHITE}Project Root Detected: {ROOT}{RESET}\n")

    total = len(ports)
    print(f"{BOLD}SUMMARY:{RESET}")
    print(f"  Total Ports Detected : {total}")
    print(f"  {GREEN}✅ REAL (Selesai)    : {status_counts['REAL']}{RESET}")
    print(f"  {YELLOW}⚠️ PARTIAL (Belum)   : {status_counts['PARTIAL']}{RESET}")
    print(f"  {RED}❌ MISSING (Kosong)  : {status_counts['MISSING']}{RESET}\n")

    def sort_key(p: PortInfo):
        order = {"MISSING": 0, "PARTIAL": 1, "REAL": 2}
        return order.get(p.status, 3), p.name

    sorted_ports = sorted(ports, key=sort_key)

    print(f"{BOLD}{'PORT INTERFACE':<38} {'STATUS':<10} {'ADAPTER IMPLEMENTATION'}{RESET}")
    print("-" * 85)

    for p in sorted_ports:
        if p.status == "REAL":
            st_col, st_ic = GREEN, "REAL"
        elif p.status == "PARTIAL":
            st_col, st_ic = YELLOW, "PARTIAL"
        else:
            st_col, st_ic = RED, "MISSING"

        adp_disp = p.adapter_class or "-"
        print(f"{p.name:<38} {st_col}{st_ic:<10}{RESET} {adp_disp}")

        port_rel = p.file.relative_to(ROOT)
        print(f"  ↳ Port File     : {port_rel}")

        if p.status == "PARTIAL":
            adp_rel = p.adapter_file.relative_to(ROOT)
            print(f"  {YELLOW}↳ Adapter File  : {adp_rel}{RESET}")
            print(f"  {RED}↳ Missing Mthds : {', '.join(sorted(p.missing_methods))}{RESET}")
            print(f"  {CYAN}↳ ACTION REQUIRED -> Buka {adp_rel} dan lengkapi method di atas!{RESET}")
        elif p.status == "MISSING":
            req_m = p.abstract_methods or p.methods
            print(f"  {RED}↳ Missing Mthds : ALL ({', '.join(sorted(req_m)) if req_m else 'Marker Interface'}){RESET}")
            print(f"  {MAGENTA}↳ ACTION REQUIRED -> Buat class adapter baru di adapters/secondary_impl/{RESET}")

        print("-" * 85)


def export_json(ports: list[PortInfo], filename: str):
    data = [{
        "name": p.name,
        "status": p.status,
        "module": p.module,
        "file": str(p.file.relative_to(ROOT)),
        "adapter_class": p.adapter_class,
        "adapter_file": str(p.adapter_file.relative_to(ROOT)) if p.adapter_file else None,
        "missing_methods": sorted(p.missing_methods),
        "file_to_edit": str(p.file_to_edit.relative_to(ROOT)) if p.file_to_edit else None,
    } for p in ports]

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"{GREEN}✅ Laporan JSON diexport ke: {filename}{RESET}")


def export_csv(ports: list[PortInfo], filename: str):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Port Name", "Status", "Port File", "Adapter Class", "Adapter File", "Missing Methods"])
        for p in ports:
            writer.writerow([
                p.name, p.status, str(p.file.relative_to(ROOT)),
                p.adapter_class or "",
                str(p.adapter_file.relative_to(ROOT)) if p.adapter_file else "",
                ", ".join(sorted(p.missing_methods))
            ])
    print(f"{GREEN}✅ Laporan CSV diexport ke: {filename}{RESET}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Port vs Adapter Implementation Checker")
    parser.add_argument("--json", metavar="FILE", help="Export hasil ke JSON")
    parser.add_argument("--csv", metavar="FILE", help="Export hasil ke CSV")
    parser.add_argument("--debug", action="store_true", help="Tampilkan skor kandidat untuk setiap port")
    args = parser.parse_args()

    ports, status_counts = generate_dashboard(debug=args.debug)
    print_dashboard(ports, status_counts)

    if args.json:
        export_json(ports, args.json)
    if args.csv:
        export_csv(ports, args.csv)

    # Return Exit Code CI/CD Pipeline standar
    if status_counts["MISSING"] > 0 or status_counts["PARTIAL"] > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
