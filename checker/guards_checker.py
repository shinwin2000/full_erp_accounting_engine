#!/usr/bin/env python3
"""
guards_checker.py — Guard Layer Compliance Checker v1.2
========================================================
Memeriksa semua guard di kernel/guards/ dan kernel/guards/async_guards/
apakah memenuhi kontrak:
- Wajib memiliki method check(context) atau enforce(context)
- Wajib memiliki method entity dasar (validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch)
- Jika di async_guards, check/enforce harus async
- Semua class turunan BaseEnforcer atau memiliki pola guard

Fixed v1.2:
- Menggunakan RCA dari checker.core.rca (bukan fallback)
- Mengabaikan kelas abstrak (Base*) agar hanya kelas konkret yang diperiksa

Usage:
    python -m checker.guards_checker --verbose
    python -m checker.guards_checker --json report.json
    python -m checker.guards_checker --discover
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---- Project root ----
_THIS_FILE = Path(__file__).resolve()
ROOT = _THIS_FILE.parent.parent if _THIS_FILE.parent.name == "checker" else _THIS_FILE.parent
sys.path.insert(0, str(ROOT))

# ---- RCA Engine (dari checker.core.rca) ----
try:
    from checker.core.rca import (
        Category,
        ErrorCode,
        RCAResult,
        Severity,
        analyze_exception,
        get_engine,
    )
    RCA_AVAILABLE = True
except ImportError:
    # Jika RCA tidak tersedia, kita tetap bisa jalan tanpa RCA
    RCA_AVAILABLE = False
    analyze_exception = None
    RCAResult = None

# ---- Logging ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ---- Color support ----
def _supports_ansi() -> bool:
    if not sys.stdout.isatty():
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
                return True
        except Exception:
            return False
    return True

_USE_COLOR = _supports_ansi()
COLOR = {
    "RED": "\033[91m" if _USE_COLOR else "",
    "GREEN": "\033[92m" if _USE_COLOR else "",
    "YELLOW": "\033[93m" if _USE_COLOR else "",
    "CYAN": "\033[96m" if _USE_COLOR else "",
    "BOLD": "\033[1m" if _USE_COLOR else "",
    "RESET": "\033[0m" if _USE_COLOR else "",
}

# ---- Data structures ----
@dataclass
class MethodInfo:
    name: str
    is_async: bool = False

@dataclass
class ClassInfo:
    name: str
    base_names: list[str]
    methods: dict[str, MethodInfo]
    file_path: str
    is_async_guard: bool = False
    is_abstract: bool = False

@dataclass
class GuardContract:
    class_name: str
    file_path: str
    has_check_or_enforce: bool
    check_is_async: bool
    has_validate: bool
    has_to_dict: bool
    has_from_dict: bool
    has_clone: bool
    has_snapshot: bool
    has_version: bool
    has_audit_trail: bool
    has_touch: bool
    violations: list[str] = field(default_factory=list)
    rca_results: list[dict[str, Any]] = field(default_factory=list)

@dataclass
class GuardViolation:
    file_path: str
    guard_name: str
    severity: str
    message: str
    suggestion: str
    rca_result: dict[str, Any] | None = None

# ---- AST Analyzer for guards ----
class GuardASTAnalyzer:
    @staticmethod
    def analyze(file_path: Path, content: str) -> list[ClassInfo]:
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []

        classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Ambil base class names
                base_names = []
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        base_names.append(base.id)
                    elif isinstance(base, ast.Attribute):
                        base_names.append(base.attr)

                # Cek apakah kelas abstrak (nama dimulai "Base" atau memiliki abstractmethod)
                is_abstract = node.name.startswith("Base")
                if not is_abstract:
                    # Periksa apakah ada method dengan decorator abstractmethod
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            for dec in item.decorator_list:
                                dec_name = None
                                if isinstance(dec, ast.Name):
                                    dec_name = dec.id
                                elif isinstance(dec, ast.Attribute):
                                    dec_name = dec.attr
                                if dec_name == "abstractmethod":
                                    is_abstract = True
                                    break
                        if is_abstract:
                            break

                # Kumpulkan method
                methods = {}
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        is_async = isinstance(item, ast.AsyncFunctionDef)
                        methods[item.name] = MethodInfo(name=item.name, is_async=is_async)

                # Cek apakah ini guard (berdasarkan inheritance atau pola)
                is_guard = (
                    "BaseEnforcer" in base_names or
                    "Guard" in node.name or
                    "Enforcer" in node.name or
                    any(m in methods for m in ("check", "enforce"))
                )
                # Abaikan kelas abstrak untuk deteksi guard
                if is_guard and not is_abstract:
                    classes.append(ClassInfo(
                        name=node.name,
                        base_names=base_names,
                        methods=methods,
                        file_path=str(file_path),
                        is_abstract=is_abstract,
                    ))
        return classes

# ---- Checker engine ----
class GuardsChecker:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self._results: list[GuardContract] = []
        self._rca_enabled = RCA_AVAILABLE

    def _get_guard_files(self) -> list[Path]:
        guard_dirs = [
            self.root_dir / "kernel" / "guards",
            self.root_dir / "kernel" / "guards" / "async_guards",
        ]
        files = []
        for base_dir in guard_dirs:
            if not base_dir.exists():
                continue
            for p in base_dir.rglob("*.py"):
                if p.name.startswith(("__init__", "test_", "conftest")):
                    continue
                if p.name in ("guard_exceptions.py", "base.py"):
                    continue
                files.append(p)
        return files

    def _is_async_guard_file(self, file_path: Path) -> bool:
        return "async_guards" in str(file_path)

    def scan_file(self, file_path: Path, discover: bool = False) -> GuardContract | None:
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            return None

        classes = GuardASTAnalyzer.analyze(file_path, content)
        if not classes:
            return None

        is_async = self._is_async_guard_file(file_path)

        # Ambil class pertama (biasanya satu class konkret per file)
        cls_info = classes[0]
        methods = cls_info.methods

        contract = GuardContract(
            class_name=cls_info.name,
            file_path=str(file_path.relative_to(self.root_dir)),
            has_check_or_enforce=False,
            check_is_async=False,
            has_validate=False,
            has_to_dict=False,
            has_from_dict=False,
            has_clone=False,
            has_snapshot=False,
            has_version=False,
            has_audit_trail=False,
            has_touch=False,
        )

        # Periksa method utama
        if "check" in methods:
            contract.has_check_or_enforce = True
            contract.check_is_async = methods["check"].is_async
        elif "enforce" in methods:
            contract.has_check_or_enforce = True
            contract.check_is_async = methods["enforce"].is_async

        # Periksa entity methods
        contract.has_validate = "validate" in methods
        contract.has_to_dict = "to_dict" in methods
        contract.has_from_dict = "from_dict" in methods
        contract.has_clone = "clone" in methods
        contract.has_snapshot = "snapshot" in methods
        contract.has_version = "version" in methods
        contract.has_audit_trail = "audit_trail" in methods
        contract.has_touch = "touch" in methods

        # Kumpulkan pelanggaran
        violations = []
        if not contract.has_check_or_enforce:
            violations.append("Method check() atau enforce() tidak ditemukan")
        else:
            if is_async and not contract.check_is_async:
                violations.append("Guard di async_guards harus memiliki method check/enforce yang async")
            elif not is_async and contract.check_is_async:
                violations.append("Guard di guards/ (sync) tidak boleh memiliki method async")

        # Entity methods yang wajib (semua)
        required_entity = ["validate", "to_dict", "from_dict", "clone", "snapshot", "version", "audit_trail", "touch"]
        for m in required_entity:
            if not getattr(contract, f"has_{m}"):
                violations.append(f"Method {m}() tidak ditemukan")

        contract.violations = violations

        if discover:
            print(f"\n📄 {contract.file_path}")
            print(f"  └─ Class: {contract.class_name}")
            status = "✅ OK" if not violations else "❌ VIOLATIONS"
            print(f"     Status: {status}")
            if violations:
                for v in violations:
                    print(f"        - {v}")
        return contract

    def scan(self, discover: bool = False) -> list[GuardContract]:
        files = self._get_guard_files()
        self._results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_file = {executor.submit(self.scan_file, f, discover): f for f in files}
            for future in concurrent.futures.as_completed(future_to_file):
                result = future.result()
                if result:
                    self._results.append(result)
        return self._results

    def analyze_with_rca(self, contract: GuardContract) -> list[GuardViolation]:
        violations = []
        if not self._rca_enabled or not analyze_exception:
            # Fallback sederhana jika RCA tidak tersedia
            for v in contract.violations:
                violations.append(GuardViolation(
                    file_path=contract.file_path,
                    guard_name=contract.class_name,
                    severity="CRITICAL" if "check" in v or "enforce" in v else "HIGH",
                    message=v,
                    suggestion=self._suggest_fix(v),
                    rca_result={
                        "root_cause": v,
                        "suggested_fix": self._suggest_fix(v),
                        "confidence": 0.5,
                        "evidence": [f"Missing method in {contract.class_name}"],
                    }
                ))
            return violations

        # Gunakan RCA dari checker.core.rca
        for v in contract.violations:
            exc = RuntimeError(f"GuardViolation: {v}")
            context = {
                "guard_name": contract.class_name,
                "file": contract.file_path,
                "violation": v,
            }
            try:
                rca = analyze_exception(exc, context=context)
                if hasattr(rca, "to_dict"):
                    rca_dict = rca.to_dict()
                elif hasattr(rca, "__dict__"):
                    rca_dict = {k: str(v) for k, v in rca.__dict__.items() if not k.startswith("_")}
                else:
                    rca_dict = {"root_cause": str(rca)}
            except Exception as e:
                logger.warning(f"RCA analysis failed: {e}")
                rca_dict = {"root_cause": v, "suggested_fix": self._suggest_fix(v), "confidence": 0.5}

            violations.append(GuardViolation(
                file_path=contract.file_path,
                guard_name=contract.class_name,
                severity="CRITICAL" if "check" in v or "enforce" in v else "HIGH",
                message=v,
                suggestion=self._suggest_fix(v),
                rca_result=rca_dict,
            ))
        return violations

    def _suggest_fix(self, violation: str) -> str:
        if "check" in violation and "enforce" in violation:
            return "Tambahkan method check(context) atau enforce(context) yang sesuai."
        if "async" in violation:
            return "Ubah method menjadi async def check(self, context): ..."
        if "validate" in violation:
            return "Tambahkan method validate(self) -> dict"
        if "to_dict" in violation:
            return "Tambahkan method to_dict(self) -> dict"
        if "from_dict" in violation:
            return "Tambahkan classmethod from_dict(cls, data) -> Self"
        if "clone" in violation:
            return "Tambahkan method clone(self) -> Self"
        if "snapshot" in violation:
            return "Tambahkan method snapshot(self) -> dict"
        if "version" in violation:
            return "Tambahkan method version(self) -> int"
        if "audit_trail" in violation:
            return "Tambahkan method audit_trail(self, limit=100) -> list"
        if "touch" in violation:
            return "Tambahkan method touch(self, touched_by: str) -> Self"
        return "Perbaiki sesuai kontrak guard."

# ---- Reporting ----
def print_report(contracts: list[GuardContract], verbose: bool = False, show_rca: bool = True):
    c = COLOR
    total = len(contracts)
    if total == 0:
        print(f"\n{c['YELLOW']}Tidak ada guard ditemukan.{c['RESET']}")
        return

    # Hitung statistik
    ok = sum(1 for ct in contracts if not ct.violations)
    critical_violations = sum(1 for ct in contracts if not ct.has_check_or_enforce)
    async_mismatch = sum(1 for ct in contracts if ct.violations and "async" in "".join(ct.violations))
    missing_entity = sum(1 for ct in contracts if ct.violations and any(m in "".join(ct.violations) for m in ("validate", "to_dict", "from_dict", "clone", "snapshot", "version", "audit_trail", "touch")))

    score = (ok / total) * 100 if total else 100

    print(f"\n{c['BOLD']}{c['CYAN']}╔{'═'*72}╗")
    print("║         GUARD LAYER COMPLIANCE REPORT — v1.2            ║")
    print(f"╚{'═'*72}╝{c['RESET']}")

    print(f"\n  Total Guard Modules: {total}")
    print(f"  ✅ Fully Compliant: {ok}")
    print(f"  ❌ Violations: {total - ok}")
    if critical_violations:
        print(f"  🚨 Missing check/enforce: {critical_violations}")
    if async_mismatch:
        print(f"  ⚡ Async/sync mismatch: {async_mismatch}")
    if missing_entity:
        print(f"  📦 Missing entity methods: {missing_entity}")
    print(f"\n  🏆 Overall Guard Score: {score:.1f}%")
    print(f"  🔍 RCA Engine: {'✅ Aktif (checker.core.rca)' if RCA_AVAILABLE else '⚠️ Tidak tersedia'}")

    if total - ok > 0:
        print(f"\n{c['RED']}─── VIOLATIONS ───{c['RESET']}")
        for ct in contracts:
            if ct.violations:
                print(f"\n  {c['YELLOW']}{ct.class_name}{c['RESET']} @ {ct.file_path}")
                for v in ct.violations:
                    sev = "CRITICAL" if "check" in v or "enforce" in v else "HIGH"
                    sev_color = c["RED"] if sev == "CRITICAL" else c["YELLOW"]
                    print(f"    {sev_color}[{sev}]{c['RESET']} {v}")
                    print(f"      💡 {self._suggest_fix(v) if hasattr(self, '_suggest_fix') else 'Perbaiki sesuai kontrak'}")
                    if verbose and show_rca:
                        # Untuk RCA, kita tampilkan dari rca_result jika ada di contract
                        # Karena kita tidak menyimpan rca_results di contract, kita tampilkan sederhana
                        print(f"      🔍 RCA: Check method compliance in {ct.class_name}")
    else:
        print(f"\n{c['GREEN']}✅ Semua guard compliant!{c['RESET']}")

def save_json(contracts: list[GuardContract], path: str):
    data = {
        "timestamp": datetime.now(UTC).isoformat(),
        "version": "1.2",
        "total_guards": len(contracts),
        "compliant": [c.file_path for c in contracts if not c.violations],
        "violations": [
            {
                "guard": c.class_name,
                "file": c.file_path,
                "violations": c.violations,
            }
            for c in contracts if c.violations
        ],
        "score": (sum(1 for c in contracts if not c.violations) / len(contracts) * 100) if contracts else 100,
        "rca_enabled": RCA_AVAILABLE,
    }
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"{COLOR['GREEN']}✅ JSON exported to {path}{COLOR['RESET']}")

# ---- Main ----
def main():
    parser = argparse.ArgumentParser(description="Guard Layer Compliance Checker v1.2")
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan detail RCA")
    parser.add_argument("--json", type=str, help="Export hasil ke JSON")
    parser.add_argument("--discover", action="store_true", help="Tampilkan semua guard yang terdeteksi (dry-run)")
    parser.add_argument("--no-rca", action="store_true", help="Nonaktifkan RCA")
    args = parser.parse_args()

    checker = GuardsChecker(ROOT)
    start = time.monotonic()
    contracts = checker.scan(discover=args.discover)
    elapsed = time.monotonic() - start

    if args.discover:
        print("\n✅ Discovery complete. To run with validation, remove --discover.")
        return

    # Tampilkan laporan dengan status RCA
    show_rca = not args.no_rca and RCA_AVAILABLE
    print_report(contracts, args.verbose, show_rca=show_rca)
    if args.json:
        save_json(contracts, args.json)

    print(f"\n ⏱️ Audit Duration: {elapsed:.2f}s")

    has_error = any(c.violations for c in contracts)
    sys.exit(1 if has_error else 0)

if __name__ == "__main__":
    main()
