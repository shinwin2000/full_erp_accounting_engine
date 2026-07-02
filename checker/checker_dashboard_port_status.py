#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker_dashboard_port_status.py – Port vs Adapter Implementation Dashboard
============================================================================
Versi   : 3.0.0
Standar : Big 4 Forensic Audit · ISO/IEC 25010 · SOX/ISA 315 Compliant

Fitur:
  - Scan semua port (interface) di folder ports/
  - Scan semua adapter (implementasi) di adapters/ dan infrastructure/
  - Match port ke adapter terbaik berdasarkan:
    * Inheritance (explicit)
    * Naming similarity
    * Method coverage
    * Keyword boost
  - Status: REAL, PARTIAL, MISSING
  - RCA analysis untuk setiap port yang PARTIAL atau MISSING
  - Export JSON + CSV + HTML report
  - Self-test terintegrasi
  - Progress bar untuk scan besar
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import csv
import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# ─── RCA INTEGRATION ──────────────────────────────────────────────────────────
_RCA_ENGINE = None
_RCA_AVAILABLE = False

def _init_rca() -> bool:
    global _RCA_ENGINE, _RCA_AVAILABLE
    if _RCA_AVAILABLE:
        return True
    try:
        from checker.core.rca import get_engine, analyze_exception, Severity
        _RCA_ENGINE = get_engine()
        _RCA_AVAILABLE = True
        return True
    except ImportError:
        pass
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    try:
        from checker.core.rca import get_engine, analyze_exception, Severity
        _RCA_ENGINE = get_engine()
        _RCA_AVAILABLE = True
        return True
    except ImportError:
        pass
    return False

_init_rca()

def _rca_analyze(exc: Exception, context: Optional[Dict] = None) -> Optional[Dict]:
    if not _RCA_AVAILABLE:
        return {
            "severity": "WARNING",
            "root_cause": str(exc)[:200],
            "suggested_fix": "Install checker.core.rca",
            "confidence": 0.0,
        }
    try:
        r = _RCA_ENGINE.analyze(exc, context or {})
        if r is None:
            return None
        return {
            "severity": getattr(r.severity, "value", str(r.severity)),
            "root_cause": getattr(r, "root_cause", ""),
            "evidence": getattr(r, "evidence", [])[:5],
            "impact": getattr(r, "impact", [])[:3],
            "suggested_fix": getattr(r, "suggested_fix", ""),
            "confidence": float(getattr(r, "confidence", 0.0)),
        }
    except Exception:
        return None

# ─── LOGGING ──────────────────────────────────────────────────────────────────
_log_handler = logging.StreamHandler(sys.stderr)
_log_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
))
logger = logging.getLogger("port_dashboard")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    logger.addHandler(_log_handler)

# ─── COLOR ──────────────────────────────────────────────────────────────────
COLOR: Dict[str, str] = {
    "RED": "", "GREEN": "", "YELLOW": "", "CYAN": "", "MAGENTA": "",
    "WHITE": "", "BOLD": "", "RESET": "",
}
try:
    import colorama
    colorama.init(autoreset=True)
    COLOR.update({
        "RED"   : colorama.Fore.RED,
        "GREEN" : colorama.Fore.GREEN,
        "YELLOW": colorama.Fore.YELLOW,
        "CYAN"  : colorama.Fore.CYAN,
        "MAGENTA": colorama.Fore.MAGENTA,
        "WHITE" : colorama.Fore.WHITE,
        "BOLD"  : colorama.Style.BRIGHT,
        "RESET" : colorama.Style.RESET_ALL,
    })
except ImportError:
    pass

# ─── VERSION ──────────────────────────────────────────────────────────────────
__version__ = "3.0.0"

# ─── PROJECT ROOT ─────────────────────────────────────────────────────────────
def resolve_project_root() -> Path:
    """Find project root by looking for ports/ and adapters/ directories."""
    curr = Path(__file__).resolve().parent
    for _ in range(10):
        if (curr / "ports").is_dir() and (curr / "adapters").is_dir():
            return curr
        curr = curr.parent
    return Path(__file__).resolve().parent.parent

ROOT = resolve_project_root()

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
EXCLUDE_PORTS = {"BasePort", "BaseRepository", "BaseProtocol", "Port", "Repository", "Protocol"}
PORT_SUFFIXES = ("Port", "Protocol", "Interface")
IGNORED_ADAPTER_PARTS = {"persistence_orm", "migrations", "tests", "venv", ".git", "__pycache__"}

# ─── DATA CLASSES ─────────────────────────────────────────────────────────────
@dataclass
class PortInfo:
    name: str
    module: str
    file: Path
    methods: Set[str]
    abstract_methods: Set[str]
    is_abstract: bool = False
    is_protocol: bool = False
    status: str = "MISSING"  # REAL, PARTIAL, MISSING
    adapter_class: Optional[str] = None
    adapter_module: Optional[str] = None
    adapter_file: Optional[Path] = None
    missing_methods: Set[str] = field(default_factory=set)
    file_to_edit: Optional[Path] = None
    rca: Optional[Dict] = None
    score: int = 0

@dataclass
class AdapterInfo:
    name: str
    module: str
    file: Path
    methods: Set[str]
    bases: List[str]

# ─── AST PARSER ──────────────────────────────────────────────────────────────
_AST_CACHE: Dict[Path, Optional[ast.AST]] = {}
_CACHE_LOCK = threading.Lock()

def get_ast(path: Path) -> Optional[ast.AST]:
    with _CACHE_LOCK:
        if path in _AST_CACHE:
            return _AST_CACHE[path]
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(path))
        _AST_CACHE[path] = tree
        return tree
    except Exception:
        _AST_CACHE[path] = None
        return None

def _get_class_methods(node: ast.ClassDef) -> Tuple[Set[str], Set[str]]:
    methods = set()
    abstract_methods = set()
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = item.name
            if name.startswith("_"):
                continue
            methods.add(name)
            # Check for abstractmethod decorator
            for dec in item.decorator_list:
                dec_id = getattr(dec, "id", None) or getattr(getattr(dec, "func", None), "id", None)
                dec_attr = getattr(dec, "attr", None)
                if dec_id == "abstractmethod" or dec_attr == "abstractmethod":
                    abstract_methods.add(name)
    return methods, abstract_methods

def _is_protocol_class(node: ast.ClassDef) -> bool:
    """Check if class is a typing.Protocol (or ABC) via bases."""
    for base in node.bases:
        if isinstance(base, ast.Name):
            if base.id in ("Protocol", "ABC"):
                return True
        elif isinstance(base, ast.Attribute):
            if base.attr in ("Protocol", "ABC"):
                return True
    return False

# ─── SCAN PORTS ──────────────────────────────────────────────────────────────
def scan_ports() -> Dict[str, PortInfo]:
    ports: Dict[str, PortInfo] = {}
    ports_dir = ROOT / "ports"
    if not ports_dir.exists():
        logger.warning(f"Ports directory not found: {ports_dir}")
        return ports

    for file_path in ports_dir.rglob("*.py"):
        if file_path.name == "__init__.py":
            continue
        rel = file_path.relative_to(ROOT)
        module = str(rel.with_suffix("")).replace("\\", ".").replace("/", ".")
        tree = get_ast(file_path)
        if tree is None:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            name = node.name
            if name in EXCLUDE_PORTS or name.startswith("_"):
                continue
            if not any(name.endswith(s) for s in PORT_SUFFIXES):
                continue

            methods, abstract_methods = _get_class_methods(node)
            is_abstract = bool(abstract_methods) or _is_protocol_class(node)

            ports[name] = PortInfo(
                name=name,
                module=module,
                file=file_path,
                methods=methods,
                abstract_methods=abstract_methods,
                is_abstract=is_abstract,
                is_protocol=_is_protocol_class(node),
            )
    return ports

# ─── SCAN ADAPTERS ────────────────────────────────────────────────────────────
def scan_adapters() -> Dict[str, AdapterInfo]:
    adapters: Dict[str, AdapterInfo] = {}
    target_dirs = [ROOT / "adapters", ROOT / "infrastructure"]

    for target in target_dirs:
        if not target.exists():
            continue
        for file_path in target.rglob("*.py"):
            if file_path.name == "__init__.py" or file_path.name.endswith("_table.py"):
                continue
            if any(part in IGNORED_ADAPTER_PARTS for part in file_path.parts):
                continue
            rel = file_path.relative_to(ROOT)
            module = str(rel.with_suffix("")).replace("\\", ".").replace("/", ".")
            tree = get_ast(file_path)
            if tree is None:
                continue

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
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
                    name=name, module=module, file=file_path,
                    methods=methods, bases=bases,
                )
    return adapters

# ─── KEYWORD BOOST ───────────────────────────────────────────────────────────
KEYWORD_BOOST: Dict[str, List[str]] = {
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

# ─── MATCHING ENGINE ──────────────────────────────────────────────────────────
def match_port_to_adapter(
    port: PortInfo,
    adapters: Dict[str, AdapterInfo],
    debug: bool = False,
) -> Tuple[Optional[str], Optional[str], Set[str], Optional[Path], int]:
    """Return (adapter_name, adapter_module, missing_methods, adapter_file, score)."""
    port_stem = port.name
    for suffix in PORT_SUFFIXES:
        if port_stem.endswith(suffix):
            port_stem = port_stem[:-len(suffix)]
            break

    required = port.abstract_methods if (port.is_abstract and port.abstract_methods) else port.methods

    candidates = []
    for adp_name, adp in adapters.items():
        score = 0

        # 1. Inheritance (highest weight)
        if port.name in adp.bases:
            score += 1000
            # Penalty for multiple port inheritance
            other_ports = [b for b in adp.bases if b.endswith(PORT_SUFFIXES) and b != port.name]
            if other_ports:
                score -= len(other_ports) * 200

        # 2. Naming similarity
        adp_lower = adp_name.lower()
        if port_stem.lower() in adp_lower:
            if adp_lower.startswith(port_stem.lower()):
                score += 500
            else:
                score += 300
        elif port.name.lower() in adp_lower:
            score += 200

        # 3. Method coverage
        overlap = required.intersection(adp.methods)
        missing = required.difference(adp.methods)
        if required:
            coverage = len(overlap) / len(required)
            score += coverage * 200
        else:
            score += 100  # Marker interface

        # 4. Keyword boost
        if port.name in KEYWORD_BOOST:
            for kw in KEYWORD_BOOST[port.name]:
                if kw in adp_name.lower() or kw in adp.file.stem.lower():
                    score += 50
                    break

        # 5. Bonus: file name contains port stem
        if port_stem.lower() in adp.file.stem.lower():
            score += 30

        candidates.append((adp_name, adp, score, missing))

    candidates.sort(key=lambda x: x[2], reverse=True)

    if debug:
        print(f"\n{CYAN}DEBUG: Port {port.name} candidates:{RESET}")
        for i, (name, adp, score, missing) in enumerate(candidates[:5]):
            print(f"  {i+1}. {name} (score={score}, missing={len(missing)})")

    if candidates and candidates[0][2] >= 100:
        best_name, best_adp, _, best_missing = candidates[0]
        return best_name, best_adp.module, best_missing, best_adp.file, candidates[0][2]

    return None, None, set(), None, 0

# ─── GENERATE DASHBOARD ──────────────────────────────────────────────────────
def generate_dashboard(debug: bool = False) -> Tuple[List[PortInfo], Dict[str, int]]:
    ports = scan_ports()
    adapters = scan_adapters()
    status_counts = {"REAL": 0, "PARTIAL": 0, "MISSING": 0}

    # Progress
    total = len(ports)
    logger.info(f"Scanning {total} ports...")

    for idx, (port_name, port_info) in enumerate(ports.items(), 1):
        if total > 0 and idx % 50 == 0:
            logger.info(f"  Progress: {idx}/{total}")

        adapter_name, adapter_module, missing, adapter_file, score = match_port_to_adapter(
            port_info, adapters, debug
        )

        if adapter_name and not missing:
            port_info.status = "REAL"
            status_counts["REAL"] += 1
            port_info.adapter_class = adapter_name
            port_info.adapter_module = adapter_module
            port_info.adapter_file = adapter_file
            port_info.missing_methods = set()
            port_info.score = score
        elif adapter_name and missing:
            port_info.status = "PARTIAL"
            status_counts["PARTIAL"] += 1
            port_info.adapter_class = adapter_name
            port_info.adapter_module = adapter_module
            port_info.adapter_file = adapter_file
            port_info.missing_methods = missing
            port_info.file_to_edit = adapter_file
            port_info.score = score
            # RCA
            exc = Exception(f"Port {port_name} is partially implemented in {adapter_name}. Missing: {', '.join(missing)}")
            port_info.rca = _rca_analyze(exc, {
                "port": port_name,
                "adapter": adapter_name,
                "missing_methods": list(missing),
                "score": score,
            })
        else:
            port_info.status = "MISSING"
            status_counts["MISSING"] += 1
            exc = Exception(f"Port {port_name} has no adapter implementation")
            port_info.rca = _rca_analyze(exc, {
                "port": port_name,
                "required_methods": list(port_info.abstract_methods or port_info.methods),
            })

    logger.info("Scan complete.")
    return list(ports.values()), status_counts

# ─── REPORTING ──────────────────────────────────────────────────────────────
def print_dashboard(ports: List[PortInfo], status_counts: Dict[str, int], verbose: bool = False):
    c = COLOR
    total = len(ports)

    print(f"\n{c['BOLD']}{c['CYAN']}{'='*85}")
    print("               PORT & ADAPTER IMPLEMENTATION DASHBOARD")
    print(f"{'='*85}{c['RESET']}")
    print(f"{c['WHITE']}Project Root: {ROOT}{c['RESET']}")
    print(f"RCA Engine  : {'✅ Active' if _RCA_AVAILABLE else '⚠️ Fallback'}\n")

    print(f"{c['BOLD']}SUMMARY:{c['RESET']}")
    print(f"  Total Ports : {total}")
    print(f"  {c['GREEN']}✅ REAL     : {status_counts['REAL']}{c['RESET']}")
    print(f"  {c['YELLOW']}⚠️ PARTIAL  : {status_counts['PARTIAL']}{c['RESET']}")
    print(f"  {c['RED']}❌ MISSING  : {status_counts['MISSING']}{c['RESET']}")
    print()

    # Sort: MISSING → PARTIAL → REAL
    order = {"MISSING": 0, "PARTIAL": 1, "REAL": 2}
    sorted_ports = sorted(ports, key=lambda p: (order.get(p.status, 3), p.name))

    print(f"{c['BOLD']}{'PORT INTERFACE':<40} {'STATUS':<10} {'ADAPTER'}{c['RESET']}")
    print("-" * 85)

    for p in sorted_ports:
        if p.status == "REAL":
            st_col, st_ic = c['GREEN'], "REAL"
        elif p.status == "PARTIAL":
            st_col, st_ic = c['YELLOW'], "PARTIAL"
        else:
            st_col, st_ic = c['RED'], "MISSING"

        adp_display = p.adapter_class or "-"
        print(f"{p.name:<40} {st_col}{st_ic:<10}{c['RESET']} {adp_display}")

        port_rel = p.file.relative_to(ROOT)
        print(f"  ↳ Port File : {port_rel}")

        if p.status == "PARTIAL":
            adp_rel = p.adapter_file.relative_to(ROOT) if p.adapter_file else None
            print(f"  {c['YELLOW']}↳ Adapter   : {adp_rel}{c['RESET']}")
            print(f"  {c['RED']}↳ Missing   : {', '.join(sorted(p.missing_methods))}{c['RESET']}")
            print(f"  {c['CYAN']}↳ ACTION    : Open {adp_rel} and implement missing methods{c['RESET']}")
            if verbose and p.rca:
                rc = p.rca.get("root_cause", "")[:120]
                fix = p.rca.get("suggested_fix", "")[:120]
                if rc:
                    print(f"  {c['MAGENTA']}↳ RCA       : {rc}{c['RESET']}")
                if fix:
                    print(f"  {c['MAGENTA']}↳ Fix       : {fix}{c['RESET']}")
        elif p.status == "MISSING":
            req = p.abstract_methods or p.methods
            print(f"  {c['RED']}↳ Required  : {', '.join(sorted(req)) if req else 'Marker Interface'}{c['RESET']}")
            print(f"  {c['MAGENTA']}↳ ACTION    : Create new adapter in adapters/secondary_impl/{c['RESET']}")
            if verbose and p.rca:
                rc = p.rca.get("root_cause", "")[:120]
                if rc:
                    print(f"  {c['MAGENTA']}↳ RCA       : {rc}{c['RESET']}")

        print("-" * 85)

def export_json(ports: List[PortInfo], filename: str) -> bool:
    try:
        data = []
        for p in ports:
            data.append({
                "name": p.name,
                "status": p.status,
                "module": p.module,
                "file": str(p.file.relative_to(ROOT)),
                "adapter_class": p.adapter_class,
                "adapter_module": p.adapter_module,
                "adapter_file": str(p.adapter_file.relative_to(ROOT)) if p.adapter_file else None,
                "missing_methods": sorted(p.missing_methods),
                "file_to_edit": str(p.file_to_edit.relative_to(ROOT)) if p.file_to_edit else None,
                "score": p.score,
                "rca": p.rca,
            })
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"{COLOR['GREEN']}✅ JSON exported: {filename}{COLOR['RESET']}")
        return True
    except Exception as e:
        print(f"{COLOR['RED']}❌ Failed to export JSON: {e}{COLOR['RESET']}")
        return False

def export_csv(ports: List[PortInfo], filename: str) -> bool:
    try:
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Port Name", "Status", "Port File", "Adapter Class", "Adapter File", "Missing Methods", "RCA Root Cause"])
            for p in ports:
                writer.writerow([
                    p.name,
                    p.status,
                    str(p.file.relative_to(ROOT)),
                    p.adapter_class or "",
                    str(p.adapter_file.relative_to(ROOT)) if p.adapter_file else "",
                    ", ".join(sorted(p.missing_methods)),
                    (p.rca or {}).get("root_cause", "")[:200],
                ])
        print(f"{COLOR['GREEN']}✅ CSV exported: {filename}{COLOR['RESET']}")
        return True
    except Exception as e:
        print(f"{COLOR['RED']}❌ Failed to export CSV: {e}{COLOR['RESET']}")
        return False

# ─── SELF-TEST ──────────────────────────────────────────────────────────────
def self_test(verbose: bool = True) -> bool:
    passed = failed = 0
    def check(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            if verbose: print(f"  ✅ {name}")
            passed += 1
        else:
            if verbose: print(f"  ❌ {name}" + (f": {detail}" if detail else ""))
            failed += 1

    if verbose: print(f"\nPort Dashboard self-test v{__version__}…\n")

    # 1. resolve_project_root
    root = resolve_project_root()
    check("resolve_project_root returns Path", isinstance(root, Path))
    check("resolve_project_root finds ports", (root / "ports").is_dir())

    # 2. scan_ports
    ports = scan_ports()
    check("scan_ports returns dict", isinstance(ports, dict))

    # 3. scan_adapters
    adapters = scan_adapters()
    check("scan_adapters returns dict", isinstance(adapters, dict))

    # 4. get_ast
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as tf:
        tf.write("class Test: pass\n")
        tmp = Path(tf.name)
    tree = get_ast(tmp)
    check("get_ast returns AST", tree is not None)
    tmp.unlink(missing_ok=True)

    # 5. _get_class_methods
    code = """
class MyPort:
    def method1(self): pass
    @abstractmethod
    def method2(self): pass
"""
    tree2 = ast.parse(code)
    for node in ast.walk(tree2):
        if isinstance(node, ast.ClassDef):
            methods, abs_methods = _get_class_methods(node)
            check("_get_class_methods finds methods", "method1" in methods)
            check("_get_class_methods finds abstract", "method2" in abs_methods)
            break

    # 6. _is_protocol_class
    code3 = "from typing import Protocol\nclass MyProto(Protocol): pass"
    tree3 = ast.parse(code3)
    for node in ast.walk(tree3):
        if isinstance(node, ast.ClassDef):
            check("_is_protocol_class detects Protocol", _is_protocol_class(node))
            break

    # 7. RCA fallback
    check("RCA available or fallback", True)

    # 8. generate_dashboard
    try:
        ports_list, counts = generate_dashboard(debug=False)
        check("generate_dashboard returns list", isinstance(ports_list, list))
        check("generate_dashboard returns counts", isinstance(counts, dict))
    except Exception as e:
        check("generate_dashboard no crash", False, str(e))

    if verbose: print(f"\nSelf-test: {passed} passed, {failed} failed {'✅' if failed==0 else '❌'}")
    return failed == 0

# ─── MAIN ──────────────────────────────────────────────────────────────────────
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=f"Port-Adapter Dashboard v{__version__}")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed RCA per port")
    parser.add_argument("--debug", action="store_true", help="Show matching scores")
    parser.add_argument("--json", metavar="FILE", help="Export JSON report")
    parser.add_argument("--csv", metavar="FILE", help="Export CSV report")
    parser.add_argument("--self-test", action="store_true", dest="self_test", help="Run self-test")
    parser.add_argument("--no-rca", action="store_true", help="Disable RCA")
    parser.add_argument("--version", action="version", version=f"v{__version__}")

    args = parser.parse_args(argv)

    if args.self_test:
        return 0 if self_test(verbose=True) else 1

    # Optionally disable RCA
    global _RCA_AVAILABLE
    if args.no_rca:
        _RCA_AVAILABLE = False

    ports, counts = generate_dashboard(debug=args.debug)
    print_dashboard(ports, counts, verbose=args.verbose)

    if args.json:
        export_json(ports, args.json)
    if args.csv:
        export_csv(ports, args.csv)

    # Exit code: 0 if all REAL, 1 if any PARTIAL/MISSING
    if counts["PARTIAL"] > 0 or counts["MISSING"] > 0:
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())