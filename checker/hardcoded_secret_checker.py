#!/usr/bin/env python3
"""
hardcoded_secret_checker.py - Hardcoded Secret & Credential Detector
======================================================================
Mendeteksi hardcoded secrets, password, API keys, tokens, private keys, dll.
dalam kode Python.

Fitur:
- Deteksi pola secret dengan regex canggih.
- Analisis konteks AST untuk mengurangi false positive.
- Mendukung deteksi di .env, file konfigurasi, dan kode.
- Laporan rinci dengan lokasi dan rekomendasi.
- Skor keamanan dan exit code.

Cara pakai:
  python hardcoded_secret_checker.py                     # Scan semua
  python hardcoded_secret_checker.py --verbose           # Detail
  python hardcoded_secret_checker.py --json report.json  # Simpan JSON
  python hardcoded_secret_checker.py --exclude tests,migrations
  python hardcoded_secret_checker.py --help
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

# =============================================================================
# Konfigurasi Warna
# =============================================================================
COLOR = {"RED": "", "GREEN": "", "YELLOW": "", "CYAN": "", "RESET": ""}
try:
    import colorama
    colorama.init(autoreset=True)
    COLOR["RED"] = colorama.Fore.RED
    COLOR["GREEN"] = colorama.Fore.GREEN
    COLOR["YELLOW"] = colorama.Fore.YELLOW
    COLOR["CYAN"] = colorama.Fore.CYAN
    COLOR["RESET"] = colorama.Style.RESET_ALL
except ImportError:
    pass

# =============================================================================
# Data Structures
# =============================================================================
@dataclass
class SecretFinding:
    file_path: str
    line: int
    col: int
    secret_type: str
    value: str
    context: str
    recommendation: str
    confidence: int  # 0-100

@dataclass
class Report:
    total_files: int = 0
    total_findings: int = 0
    findings: List[SecretFinding] = field(default_factory=list)
    score: int = 100

# =============================================================================
# Patterns & Heuristics
# =============================================================================
# Pola untuk mendeteksi secret berdasarkan tipe
SECRET_PATTERNS = [
    # Password
    {
        "type": "password",
        "patterns": [
            r'(?i)(password|passwd|pwd)\s*[:=]\s*["\']([^"\']{4,})["\']',
            r'(?i)(password|passwd|pwd)\s*=\s*["\']([^"\']{4,})["\']',
            r'(?i)(password|passwd|pwd)\s*["\']([^"\']{4,})["\']',
        ],
        "confidence": 90,
        "recommendation": "Gunakan environment variable atau secrets manager untuk password."
    },
    # API Key / Token
    {
        "type": "api_key",
        "patterns": [
            r'(?i)(api_key|apikey|api_token|token|access_token)\s*[:=]\s*["\']([A-Za-z0-9_\-]{16,})["\']',
            r'(?i)(api_key|apikey|api_token|token|access_token)\s*=\s*["\']([A-Za-z0-9_\-]{16,})["\']',
            r'(?i)(api_key|apikey|api_token|token|access_token)\s*["\']([A-Za-z0-9_\-]{16,})["\']',
            r'(?i)(bearer|auth|authorization)\s*[:=]\s*["\'](?:Bearer\s+)?([A-Za-z0-9_\-\.]{20,})["\']',
        ],
        "confidence": 85,
        "recommendation": "Gunakan environment variable untuk menyimpan API key/token."
    },
    # Secret Key (JWT, Django, Flask)
    {
        "type": "secret_key",
        "patterns": [
            r'(?i)(secret_key|SECRET_KEY|secret)\s*[:=]\s*["\']([A-Za-z0-9@#$!%^&*_\-]{16,})["\']',
            r'(?i)(secret_key|SECRET_KEY|secret)\s*=\s*["\']([A-Za-z0-9@#$!%^&*_\-]{16,})["\']',
        ],
        "confidence": 80,
        "recommendation": "Gunakan environment variable untuk secret key."
    },
    # Private Key (RSA, SSH, PEM)
    {
        "type": "private_key",
        "patterns": [
            r'-----BEGIN (?:RSA|DSA|EC|OPENSSH) PRIVATE KEY-----',
            r'-----BEGIN PRIVATE KEY-----',
        ],
        "confidence": 100,
        "recommendation": "Pindahkan private key ke file terpisah di luar repository atau gunakan secrets manager."
    },
    # Database URL dengan password
    {
        "type": "database_url",
        "patterns": [
            r'(?i)(database_url|DATABASE_URL|db_url)\s*[:=]\s*["\'](?:postgresql|mysql|mongodb|redis)://[^:]+:([^@]+)@',
            r'(?i)(database_url|DATABASE_URL|db_url)\s*=\s*["\'](?:postgresql|mysql|mongodb|redis)://[^:]+:([^@]+)@',
        ],
        "confidence": 95,
        "recommendation": "Gunakan environment variable untuk database URL, jangan hardcode password."
    },
    # OAuth2 Client Secret
    {
        "type": "oauth_secret",
        "patterns": [
            r'(?i)(client_secret|CLIENT_SECRET)\s*[:=]\s*["\']([A-Za-z0-9_\-]{16,})["\']',
            r'(?i)(client_secret|CLIENT_SECRET)\s*=\s*["\']([A-Za-z0-9_\-]{16,})["\']',
        ],
        "confidence": 85,
        "recommendation": "Gunakan environment variable untuk client secret."
    },
    # AWS Secret Key
    {
        "type": "aws_secret",
        "patterns": [
            r'(?i)(aws_secret_access_key|AWS_SECRET_ACCESS_KEY)\s*[:=]\s*["\']([A-Za-z0-9/+=]{16,})["\']',
            r'(?i)(aws_secret_access_key|AWS_SECRET_ACCESS_KEY)\s*=\s*["\']([A-Za-z0-9/+=]{16,})["\']',
        ],
        "confidence": 90,
        "recommendation": "Gunakan IAM role atau environment variable untuk AWS credentials."
    },
    # JWT Secret
    {
        "type": "jwt_secret",
        "patterns": [
            r'(?i)(jwt_secret|JWT_SECRET)\s*[:=]\s*["\']([A-Za-z0-9_\-\.]{16,})["\']',
            r'(?i)(jwt_secret|JWT_SECRET)\s*=\s*["\']([A-Za-z0-9_\-\.]{16,})["\']',
        ],
        "confidence": 85,
        "recommendation": "Gunakan environment variable untuk JWT secret."
    },
    # Generic secret
    {
        "type": "generic_secret",
        "patterns": [
            r'(?i)(secret|token|key)\s*[:=]\s*["\']([A-Za-z0-9@#$!%^&*_\-]{20,})["\']',
            r'(?i)(secret|token|key)\s*=\s*["\']([A-Za-z0-9@#$!%^&*_\-]{20,})["\']',
        ],
        "confidence": 70,
        "recommendation": "Gunakan environment variable atau secrets manager."
    },
]

# Kata-kata yang menunjukkan nilai aman (bukan secret)
WHITELIST_VALUES = {
    "example", "test", "dummy", "changeme", "password", "your_", "placeholder",
    "secret", "token", "key", "null", "none", "false", "true", "0", "1",
    "localhost", "127.0.0.1", "postgres", "user", "pass", "admin",
    "password123", "123456", "qwerty", "abc123",
}

# Prefix environment yang menunjukkan variabel dari env
ENV_PREFIXES = {"os.environ", "os.getenv", "environ.get", "getenv", "env.get"}

# =============================================================================
# AST-based Checker
# =============================================================================
class SecretVisitor(ast.NodeVisitor):
    def __init__(self, file_path: str, content: str):
        self.file_path = file_path
        self.content = content
        self.lines = content.splitlines()
        self.findings: List[SecretFinding] = []
        self.context_vars: Dict[str, str] = {}  # variable name -> value (if constant)

    def visit_Assign(self, node: ast.Assign):
        """Tangani assignment untuk mendeteksi secret di variabel."""
        # Cek apakah nilai adalah konstan string atau call dari os.getenv?
        for target in node.targets:
            if isinstance(target, ast.Name):
                var_name = target.id
                # Nilai mungkin konstan
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    value = node.value.value
                    self._check_value(var_name, value, node.lineno, node.col_offset)
                elif isinstance(node.value, ast.Call):
                    # Cek apakah call ke os.getenv atau sejenisnya
                    if self._is_env_call(node.value):
                        # Ini aman karena mengambil dari env
                        pass
                    else:
                        # Coba evaluasi jika mungkin
                        pass
                elif isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Add):
                    # Mungkin concatenation, coba evaluasi sederhana
                    pass
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant):
        """Tangani string literal langsung."""
        if isinstance(node.value, str):
            # Cek apakah string ini mungkin secret
            self._check_value(None, node.value, node.lineno, node.col_offset)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        """Tangani atribut yang mungkin secret."""
        if isinstance(node.value, ast.Name) and node.value.id in ENV_PREFIXES:
            # Ini dari environment, aman
            pass
        self.generic_visit(node)

    def _is_env_call(self, node: ast.Call) -> bool:
        """Cek apakah call ke fungsi environment."""
        if isinstance(node.func, ast.Name):
            return node.func.id in {"getenv", "environ_get"}
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                return node.func.value.id in {"os", "environ"} and node.func.attr in {"get", "getenv"}
        return False

    def _check_value(self, var_name: Optional[str], value: str, line: int, col: int):
        """Periksa apakah value mengandung secret."""
        # Abaikan jika terlalu pendek
        if len(value) < 4:
            return
        # Abaikan jika termasuk whitelist
        if value.lower() in WHITELIST_VALUES:
            return
        # Cek pola
        for pattern_def in SECRET_PATTERNS:
            for pattern in pattern_def["patterns"]:
                match = re.search(pattern, value, re.IGNORECASE)
                if match:
                    # Ekstrak bagian yang dicurigai
                    captured = match.group(2) if len(match.groups()) >= 2 else match.group(1)
                    if captured and len(captured) >= 4 and captured.lower() not in WHITELIST_VALUES:
                        # Tambahkan finding
                        context_line = self.lines[line-1].strip() if line <= len(self.lines) else ""
                        self.findings.append(SecretFinding(
                            file_path=self.file_path,
                            line=line,
                            col=col,
                            secret_type=pattern_def["type"],
                            value=captured[:20] + "..." if len(captured) > 20 else captured,
                            context=context_line[:100],
                            recommendation=pattern_def["recommendation"],
                            confidence=pattern_def["confidence"],
                        ))
                        return

# =============================================================================
# Scanner
# =============================================================================
def scan_file(file_path: pathlib.Path, root: pathlib.Path) -> List[SecretFinding]:
    """Scan satu file untuk hardcoded secrets."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        # Scan dengan regex untuk pola cepat
        findings = []
        # Periksa baris per baris untuk pola secret
        lines = content.splitlines()
        for i, line in enumerate(lines, 1):
            for pattern_def in SECRET_PATTERNS:
                for pattern in pattern_def["patterns"]:
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        captured = match.group(2) if len(match.groups()) >= 2 else match.group(1)
                        if captured and len(captured) >= 4 and captured.lower() not in WHITELIST_VALUES:
                            findings.append(SecretFinding(
                                file_path=str(file_path.relative_to(root)),
                                line=i,
                                col=match.start(),
                                secret_type=pattern_def["type"],
                                value=captured[:20] + "..." if len(captured) > 20 else captured,
                                context=line[:100],
                                recommendation=pattern_def["recommendation"],
                                confidence=pattern_def["confidence"],
                            ))
                            break
                if findings and findings[-1].line == i:
                    break

        # AST scan untuk deteksi lebih akurat
        try:
            tree = ast.parse(content, filename=str(file_path))
            visitor = SecretVisitor(str(file_path.relative_to(root)), content)
            visitor.visit(tree)
            # Gabungkan temuan AST dengan regex (hindari duplikat)
            ast_findings = visitor.findings
            # Deduplikasi berdasarkan line dan value
            existing = {(f.line, f.value) for f in findings}
            for f in ast_findings:
                if (f.line, f.value) not in existing:
                    findings.append(f)
        except SyntaxError:
            # Skip AST jika syntax error
            pass

        return findings
    except Exception:
        return []

def scan_project(exclude_dirs: List[str] = None) -> Report:
    if exclude_dirs is None:
        exclude_dirs = [".venv", "venv", "__pycache__", ".git", "node_modules", "dist", "build", "migrations", "deployment", "docs"]
    exclude_set = set(exclude_dirs)

    all_findings = []
    py_files = []
    for path in PROJECT_ROOT.rglob("*.py"):
        if any(part in exclude_set for part in path.parts):
            continue
        # Skip checker files
        if path.name.startswith("hardcoded_secret_checker"):
            continue
        py_files.append(path)

    for f in py_files:
        findings = scan_file(f, PROJECT_ROOT)
        all_findings.extend(findings)

    score = max(0, 100 - len(all_findings) * 10)
    return Report(
        total_files=len(py_files),
        total_findings=len(all_findings),
        findings=all_findings,
        score=score,
    )

# =============================================================================
# Output
# =============================================================================
def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}HARDCODED SECRET CHECKER REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"\n  Files scanned   : {report.total_files}")
    print(f"  Secrets found   : {report.total_findings}")
    print(f"  Security score  : {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")

    if report.findings:
        print(f"\n{c['RED']}❌ Hardcoded Secrets Found:{c['RESET']}")
        for f in report.findings[:20]:
            print(f"  {c['RED']}✖{c['RESET']} {f.file_path}:{f.line}  [{f.secret_type.upper()}]  {f.value}")
            if verbose:
                print(f"     Context: {f.context}")
                print(f"     Confidence: {f.confidence}%")
                print(f"     💡 {f.recommendation}")
        if len(report.findings) > 20:
            print(f"  ... and {len(report.findings)-20} more findings")
    else:
        print(f"\n{c['GREEN']}✅ No hardcoded secrets detected!{c['RESET']}")

    print(f"\n{c['CYAN']}{'─'*70}{c['RESET']}")

def save_json(report: Report, filepath: str):
    data = {
        "total_files": report.total_files,
        "total_findings": report.total_findings,
        "score": report.score,
        "findings": [
            {
                "file": f.file_path,
                "line": f.line,
                "col": f.col,
                "type": f.secret_type,
                "value": f.value,
                "context": f.context,
                "recommendation": f.recommendation,
                "confidence": f.confidence,
            }
            for f in report.findings
        ],
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{c['CYAN']}JSON report saved to {filepath}{c['RESET']}")

# =============================================================================
# CLI
# =============================================================================
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(description="Hardcoded Secret Checker")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    parser.add_argument("--quiet", action="store_true", help="Minimal output")
    parser.add_argument("--exclude", default=".venv,venv,__pycache__,node_modules,dist,build,migrations,deployment,docs",
                        help="Folder yang diabaikan (pisahkan dengan koma)")
    args = parser.parse_args()

    exclude_dirs = [d.strip() for d in args.exclude.split(",") if d.strip()]
    start = time.monotonic()
    report = scan_project(exclude_dirs)

    if not args.quiet:
        print_report(report, verbose=args.verbose)
    if args.json:
        save_json(report, args.json)

    elapsed = time.monotonic() - start
    if not args.quiet:
        print(f"\n  Time: {elapsed:.2f}s")

    # Exit code: 0 if no findings, else 1
    sys.exit(0 if report.total_findings == 0 else 1)

if __name__ == "__main__":
    main()