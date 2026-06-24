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

Cara pakai:
    python checker_dashboard_port_status.py [--json report.json] [--csv report.csv]
"""

import ast
import json
import csv
import sys
from pathlib import Path
from typing import Dict, Set, List, Optional, Tuple
from dataclasses import dataclass, field

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


ROOT = Path(__file__).resolve().parent
PORTS_PRIMARY = ROOT / "ports" / "primary"
PORTS_SECONDARY = ROOT / "ports" / "secondary"
ADAPTERS_IMPL = ROOT / "adapters" / "secondary_impl"
ADAPTERS_API = ROOT / "adapters" / "primary_api"

EXCLUDE_PORTS = {"BasePort", "BaseRepository", "BaseProtocol", "Port", "Repository", "Protocol"}


@dataclass
class PortInfo:
    name: str
    module: str
    file: Path
    methods: Set[str]
    abstract_methods: Set[str]
    is_abstract: bool = False
    status: str = "MISSING"  # REAL, PARTIAL, MISSING
    adapter_class: Optional[str] = None
    adapter_module: Optional[str] = None
    adapter_file: Optional[Path] = None
    missing_methods: Set[str] = field(default_factory=set)
    # Rekomendasi file yang harus diedit
    file_to_edit: Optional[Path] = None


@dataclass
class AdapterInfo:
    name: str
    module: str
    file: Path
    methods: Set[str]
    bases: List[str]


# ============================================================================
# 1. SCAN PORTS
# ============================================================================

def get_all_ports() -> Dict[str, PortInfo]:
    ports = {}
    for base_dir in [PORTS_PRIMARY, PORTS_SECONDARY]:
        if not base_dir.exists():
            continue
        for file_path in base_dir.glob("*.py"):
            if file_path.name == "__init__.py":
                continue
            module_path = str(file_path.relative_to(ROOT).with_suffix("")).replace("\\", ".").replace("/", ".")
            try:
                tree = ast.parse(file_path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        name = node.name
                        if name in EXCLUDE_PORTS:
                            continue
                        if not (name.endswith("Port") or name.endswith("Protocol") or name.endswith("Repository")):
                            continue
                        methods = set()
                        abstract_methods = set()
                        for item in node.body:
                            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                method_name = item.name
                                if method_name.startswith("_"):
                                    continue
                                methods.add(method_name)
                                is_abstract = False
                                for dec in item.decorator_list:
                                    if isinstance(dec, ast.Name) and dec.id == "abstractmethod":
                                        is_abstract = True
                                    elif isinstance(dec, ast.Attribute) and dec.attr == "abstractmethod":
                                        is_abstract = True
                                if is_abstract:
                                    abstract_methods.add(method_name)
                        is_abstract_class = False
                        for base in node.bases:
                            if isinstance(base, ast.Name) and base.id in ("ABC", "Protocol"):
                                is_abstract_class = True
                            elif isinstance(base, ast.Attribute) and base.attr in ("ABC", "Protocol"):
                                is_abstract_class = True
                        if is_abstract_class or abstract_methods:
                            is_abstract_class = True
                        info = PortInfo(
                            name=name,
                            module=module_path,
                            file=file_path,
                            methods=methods,
                            abstract_methods=abstract_methods,
                            is_abstract=is_abstract_class,
                        )
                        ports[name] = info
            except Exception as e:
                print(f"{RED}Error parsing {file_path}: {e}{RESET}")
    return ports


# ============================================================================
# 2. SCAN ADAPTERS
# ============================================================================

def get_all_adapters() -> Dict[str, AdapterInfo]:
    adapters = {}
    for base_dir in [ADAPTERS_IMPL, ADAPTERS_API]:
        if not base_dir.exists():
            continue
        for file_path in base_dir.rglob("*.py"):
            if file_path.name == "__init__.py":
                continue
            if "error" in file_path.stem.lower() or "exception" in file_path.stem.lower():
                continue
            module_path = str(file_path.relative_to(ROOT).with_suffix("")).replace("\\", ".").replace("/", ".")
            try:
                tree = ast.parse(file_path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        name = node.name
                        if "Error" in name or "Exception" in name or name.startswith("_"):
                            continue
                        methods = set()
                        for item in node.body:
                            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                if not item.name.startswith("_"):
                                    methods.add(item.name)
                        bases = []
                        for base in node.bases:
                            if isinstance(base, ast.Name):
                                bases.append(base.id)
                            elif isinstance(base, ast.Attribute):
                                bases.append(base.attr)
                        if name not in adapters:
                            adapters[name] = AdapterInfo(
                                name=name,
                                module=module_path,
                                file=file_path,
                                methods=methods,
                                bases=bases,
                            )
            except Exception:
                continue
    return adapters


# ============================================================================
# 3. MATCHING LOGIC (DIPERBAIKI DENGAN KEYWORD BOOST)
# ============================================================================

# Mapping port ke kata kunci untuk meningkatkan skor
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
    "TrialBalanceRepositoryPort": ["trial", "balance"],
    "IncomeStatementRepositoryPort": ["income", "statement"],
    "BalanceSheetRepositoryPort": ["balance", "sheet"],
    "CashFlowRepositoryPort": ["cash", "flow"],
    "InventoryValuationRepositoryPort": ["inventory", "valuation"],
    "AgingReportRepositoryPort": ["aging"],
    "CoreTaxPort": ["coretax", "tax", "core"],
    "TaxAuthorityCoretaxPort": ["coretax", "tax", "authority"],
    "TaxTransactionRepositoryPort": ["tax", "transaction"],
}


def match_port_to_adapter(port: PortInfo, adapters: Dict[str, AdapterInfo]) -> Tuple[Optional[str], Optional[str], Set[str], Optional[Path]]:
    """
    Mencocokkan port dengan adapter terbaik.
    Returns: (adapter_name, adapter_module, missing_methods, adapter_file)
    """
    base_name = port.name.replace("Port", "").replace("Protocol", "").replace("Repository", "")
    base_lower = base_name.lower()

    required_methods = port.abstract_methods if port.is_abstract and port.abstract_methods else port.methods
    if not required_methods:
        return None, None, set(), None

    best_adapter = None
    best_module = None
    best_score = -1
    best_missing = set()
    best_file = None

    for adp_name, adp_info in adapters.items():
        inherits = port.name in adp_info.bases
        name_match = base_lower in adp_name.lower() or port.name.lower() in adp_name.lower()
        score = 0
        if inherits:
            score += 100
        if name_match:
            score += 30
        adp_methods = adp_info.methods
        missing = required_methods - adp_methods
        overlap = len(required_methods & adp_methods)
        score += overlap * 5
        if missing:
            score -= len(missing) * 2
        if "secondary_impl" in adp_info.module:
            score += 10
        if adp_methods == {"__init__"}:
            score -= 20

        # Boost berdasarkan kata kunci
        if port.name in KEYWORD_BOOST:
            for kw in KEYWORD_BOOST[port.name]:
                if kw in adp_name.lower() or kw in adp_info.file.stem.lower():
                    score += 30
                    break

        if score > best_score:
            best_score = score
            best_adapter = adp_name
            best_module = adp_info.module
            best_missing = missing
            best_file = adp_info.file

    if best_adapter and best_score >= 0:
        return best_adapter, best_module, best_missing, best_file
    return None, None, set(), None


# ============================================================================
# 4. DASHBOARD
# ============================================================================

def generate_dashboard() -> Tuple[List[PortInfo], Dict[str, int]]:
    ports = get_all_ports()
    adapters = get_all_adapters()

    status_counts = {"REAL": 0, "PARTIAL": 0, "MISSING": 0}
    for port_name, port_info in ports.items():
        adapter_name, adapter_module, missing, adapter_file = match_port_to_adapter(port_info, adapters)
        if adapter_name and not missing:
            port_info.status = "REAL"
            status_counts["REAL"] += 1
            port_info.adapter_class = adapter_name
            port_info.adapter_module = adapter_module
            port_info.adapter_file = adapter_file
            port_info.missing_methods = set()
            port_info.file_to_edit = None
        elif adapter_name and missing:
            port_info.status = "PARTIAL"
            status_counts["PARTIAL"] += 1
            port_info.adapter_class = adapter_name
            port_info.adapter_module = adapter_module
            port_info.adapter_file = adapter_file
            port_info.missing_methods = missing
            port_info.file_to_edit = adapter_file  # Rekomendasi file yang harus diedit
        else:
            port_info.status = "MISSING"
            status_counts["MISSING"] += 1
            port_info.adapter_class = None
            port_info.adapter_module = None
            port_info.adapter_file = None
            port_info.missing_methods = set()
            port_info.file_to_edit = None

    return list(ports.values()), status_counts


def print_dashboard(ports: List[PortInfo], status_counts: Dict[str, int]):
    print(f"{BOLD}{CYAN}╔{'═'*78}╗{RESET}")
    print(f"{BOLD}{CYAN}║{' '*22}PORT & ADAPTER DASHBOARD{' '*23}║{RESET}")
    print(f"{BOLD}{CYAN}╚{'═'*78}╝{RESET}")
    print()

    total = len(ports)
    real = status_counts["REAL"]
    partial = status_counts["PARTIAL"]
    missing = status_counts["MISSING"]

    print(f"{BOLD}SUMMARY{RESET}")
    print(f"  Total Ports: {total}")
    print(f"  {GREEN}✅ REAL:     {real}{RESET}")
    print(f"  {YELLOW}⚠️ PARTIAL:  {partial}{RESET}")
    print(f"  {RED}❌ MISSING:  {missing}{RESET}")
    print()

    def sort_key(p: PortInfo):
        order = {"MISSING": 0, "PARTIAL": 1, "REAL": 2}
        return order.get(p.status, 3), p.name

    sorted_ports = sorted(ports, key=sort_key)

    print(f"{BOLD}{'Name':<35} {'Status':<10} {'Adapter':<22} {'Missing Methods'}{RESET}")
    print("─" * 80)

    for p in sorted_ports:
        if p.status == "REAL":
            status_color = GREEN
            status_icon = "✅"
        elif p.status == "PARTIAL":
            status_color = YELLOW
            status_icon = "⚠️"
        else:
            status_color = RED
            status_icon = "❌"

        adapter_display = p.adapter_class if p.adapter_class else "-"
        if p.adapter_class and len(adapter_display) > 20:
            adapter_display = adapter_display[:18] + "…"

        if p.missing_methods:
            missing_display = ", ".join(sorted(p.missing_methods))
        else:
            missing_display = "-"

        print(f"  {status_color}{status_icon} {p.name:<34} {status_color}{p.status:<9}{RESET} {adapter_display:<22} {missing_display}")

        # File port
        if p.file:
            port_path = p.file.relative_to(ROOT)
            print(f"      📁 Port: {port_path}")

        # File adapter
        if p.adapter_file:
            adapter_path = p.adapter_file.relative_to(ROOT)
            if p.status == "PARTIAL" and p.file_to_edit:
                print(f"      📁 EDIT FILE INI: {adapter_path}  <-- TAMBAHKAN METHOD YANG HILANG")
            else:
                print(f"      📁 Adapter: {adapter_path}")

        # Jika MISSING
        if p.status == "MISSING" and not p.adapter_file:
            print(f"      ⚠️  TIDAK ADA ADAPTER - Buat file adapter baru di adapters/secondary_impl/")

        # Jika PARTIAL, tampilkan metode yang harus ditambahkan
        if p.status == "PARTIAL" and p.missing_methods:
            print(f"      🔧 Tambahkan method: {', '.join(sorted(p.missing_methods))}")

    print("\n" + "═" * 80)


def export_json(ports: List[PortInfo], filename: str):
    data = []
    for p in ports:
        data.append({
            "name": p.name,
            "status": p.status,
            "module": p.module,
            "file": str(p.file.relative_to(ROOT)),
            "methods": sorted(p.methods),
            "abstract_methods": sorted(p.abstract_methods),
            "adapter_class": p.adapter_class,
            "adapter_module": p.adapter_module,
            "adapter_file": str(p.adapter_file.relative_to(ROOT)) if p.adapter_file else None,
            "missing_methods": sorted(p.missing_methods),
            "file_to_edit": str(p.file_to_edit.relative_to(ROOT)) if p.file_to_edit else None,
        })
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"{GREEN}✅ JSON exported to {filename}{RESET}")


def export_csv(ports: List[PortInfo], filename: str):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Name", "Status", "Module", "PortFile", "AdapterClass",
            "AdapterModule", "AdapterFile", "MissingMethods", "FileToEdit"
        ])
        for p in ports:
            writer.writerow([
                p.name,
                p.status,
                p.module,
                str(p.file.relative_to(ROOT)),
                p.adapter_class or "",
                p.adapter_module or "",
                str(p.adapter_file.relative_to(ROOT)) if p.adapter_file else "",
                ", ".join(sorted(p.missing_methods)),
                str(p.file_to_edit.relative_to(ROOT)) if p.file_to_edit else "",
            ])
    print(f"{GREEN}✅ CSV exported to {filename}{RESET}")


# ============================================================================
# 5. MAIN
# ============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Port & Adapter Dashboard (full missing methods)")
    parser.add_argument("--json", metavar="FILE", help="Export to JSON")
    parser.add_argument("--csv", metavar="FILE", help="Export to CSV")
    parser.add_argument("--verbose", action="store_true", help="Show all details")
    args = parser.parse_args()

    ports, status_counts = generate_dashboard()
    print_dashboard(ports, status_counts)

    if args.json:
        export_json(ports, args.json)
    if args.csv:
        export_csv(ports, args.csv)

    if status_counts["MISSING"] > 0 or status_counts["PARTIAL"] > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()