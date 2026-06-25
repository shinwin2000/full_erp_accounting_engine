#!/usr/bin/env python3
"""
secret_scanner_checker.py - Secret Scanner (Hardcoded Secrets Detector)
=======================================================================
Mendeteksi hardcoded secrets, credentials, token, API key, private key, dll.
dengan akurasi tinggi menggunakan AST + Regex + Context-Aware.

Cara pakai:
  python secret_scanner_checker.py
  python secret_scanner_checker.py --verbose
  python secret_scanner_checker.py --json report.json
  python secret_scanner_checker.py --exclude tests,migrations,.venv
  python secret_scanner_checker.py --strict   # Tampilkan semua temuan, termasuk INFO
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

# Warna
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

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent

@dataclass
class Finding:
    file: str
    line: int
    severity: str          # CRITICAL / WARNING / INFO
    message: str
    snippet: str
    recommendation: str = ""

@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    score: int = 100

# ----------------------------------------------------------------------
# Pattern Definitions
# ----------------------------------------------------------------------
# Pola untuk mendeteksi secret di assignment
SECRET_PATTERNS = [
    # Password
    (re.compile(r'(?i)(password|passwd|pwd)\s*=\s*["\']([^"\']{8,})["\']'), "CRITICAL", "Password hardcoded"),
    (re.compile(r'(?i)(password|passwd|pwd)\s*=\s*["\']([^"\']{4,})["\']'), "WARNING", "Password hardcoded (short)"),

    # API Key / Token
    (re.compile(r'(?i)(api[_\-]?key|apikey)\s*=\s*["\']([A-Za-z0-9]{16,})["\']'), "CRITICAL", "API key hardcoded"),
    (re.compile(r'(?i)(token|access[_\-]?token|refresh[_\-]?token)\s*=\s*["\']([A-Za-z0-9_\-\.]{20,})["\']'), "CRITICAL", "Token hardcoded"),

    # Secret Key
    (re.compile(r'(?i)secret[_\-]?key\s*=\s*["\']([A-Za-z0-9@#$!%^&*_\-]{16,})["\']'), "CRITICAL", "Secret key hardcoded"),

    # JWT Secret
    (re.compile(r'(?i)jwt[_\-]?secret\s*=\s*["\']([A-Za-z0-9]{32,})["\']'), "CRITICAL", "JWT secret hardcoded"),

    # Private / Public Key (PEM format)
    (re.compile(r'(?i)(private_key|public_key)\s*=\s*["\'](-----BEGIN [A-Z]+ KEY-----)'), "CRITICAL", "Private/Public key hardcoded"),
    (re.compile(r'(?i)(private_key|public_key)\s*=\s*["\']([^"\']{40,})["\']'), "WARNING", "Potentially long key value"),

    # Database URL with password
    (re.compile(r'(?i)database[_\-]?url\s*=\s*["\'](postgresql|mysql|mongodb)://[^:]+:([^@]+)@'), "CRITICAL", "Database URL with password"),

    # Redis URL with password
    (re.compile(r'(?i)redis[_\-]?url\s*=\s*["\']redis://[^:]+:([^@]+)@'), "CRITICAL", "Redis URL with password"),

    # Generic secret assignment
    (re.compile(r'(?i)(secret|credential)\s*=\s*["\']([A-Za-z0-9@#$!%^&*_\-]{20,})["\']'), "WARNING", "Generic secret hardcoded"),
]

# Pola untuk mendeteksi secret di komentar (opsional)
COMMENT_PATTERNS = [
    (re.compile(r'(?i)(password|passwd|pwd)\s*[:=]\s*[^"\']+'), "WARNING", "Password in comment"),
    (re.compile(r'(?i)(api[_\-]?key|apikey)\s*[:=]\s*[A-Za-z0-9]{16,}'), "WARNING", "API key in comment"),
    (re.compile(r'(?i)(token|secret)\s*[:=]\s*[A-Za-z0-9]{20,}'), "WARNING", "Token/secret in comment"),
]

# Pengecualian: nilai yang dianggap aman (placeholder, example, dll.)
EXEMPT_VALUES = {
    'example', 'changeme', 'your_', 'dummy', 'test', 'placeholder', 'sample', 'demo',
    'password', 'secret', 'token', 'api_key', 'your-password', 'your-secret-key',
    'wrong_password', 'minioadmin', 'postgres', 'root', 'admin', '123456', 'password123',
}
EXEMPT_CONTAINS = {'example', 'changeme', 'your_', 'dummy', 'test', 'placeholder'}

# Status constants yang tidak perlu dianggap sebagai secret
STATUS_CONSTANTS = {
    'FAILURE_WRONG_PASSWORD', 'ERROR_', 'STATUS_', 'SUCCESS_',
    'PASSWORD_RESET', 'PASSWORD_CHANGE', 'PASSWORD_VALIDATION',
}

# ----------------------------------------------------------------------
# Core Scanner Functions
# ----------------------------------------------------------------------
def is_exempt_value(value: str) -> bool:
    """Periksa apakah nilai merupakan placeholder/example."""
    val_lower = value.lower().strip('"\'')
    if val_lower in EXEMPT_VALUES:
        return True
    for ex in EXEMPT_CONTAINS:
        if ex in val_lower:
            return True
    # Jika panjang kurang dari 4 karakter, kemungkinan bukan secret
    if len(val_lower) < 4:
        return True
    return False

def extract_value(node: ast.AST) -> Optional[str]:
    """Ekstrak nilai string dari node AST."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        # String concatenation: coba evaluasi sederhana
        left = extract_value(node.left)
        right = extract_value(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        # f-string: hanya ambil literal bagian (kurang akurat, tapi bisa)
        parts = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                parts.append(part.value)
        if parts:
            return ''.join(parts)
    return None

def check_assignment(node: ast.Assign, file_path: str, lines: List[str]) -> List[Finding]:
    findings = []
    for target in node.targets:
        if not isinstance(target, ast.Name):
            continue
        var_name = target.id
        # Abaikan jika variabel adalah status constant
        if var_name in STATUS_CONSTANTS:
            continue

        # Ambil nilai
        value = extract_value(node.value)
        if value is None:
            continue
        if is_exempt_value(value):
            continue

        # Cek pattern
        for pattern, severity, msg in SECRET_PATTERNS:
            match = pattern.search(f"{var_name}={value}")
            if match:
                findings.append(Finding(
                    file=file_path,
                    line=node.lineno,
                    severity=severity,
                    message=f"{msg}: {var_name} = {value[:20]}...",
                    snippet=lines[node.lineno-1].strip()[:150] if node.lineno <= len(lines) else value[:100],
                    recommendation=f"Pindahkan {var_name} ke environment variable atau secrets manager."
                ))
                break
    return findings

def check_comment(line: str, file_path: str, lineno: int) -> List[Finding]:
    """Cek apakah komentar mengandung secret."""
    findings = []
    # Ambil teks setelah # atau """
    comment = line.split('#', 1)[-1].strip()
    if not comment:
        return findings
    for pattern, severity, msg in COMMENT_PATTERNS:
        if pattern.search(comment):
            findings.append(Finding(
                file=file_path,
                line=lineno,
                severity=severity,
                message=f"{msg}: {comment[:50]}...",
                snippet=comment[:100],
                recommendation="Hapus secret dari komentar, gunakan dokumentasi terpisah."
            ))
            break
    return findings

def check_file(file_path: pathlib.Path) -> List[Finding]:
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        lines = src.splitlines()
        tree = ast.parse(src, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return []

    findings = []
    # Scan assignment
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            findings.extend(check_assignment(node, str(file_path), lines))

    # Scan comments
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('#'):
            findings.extend(check_comment(line, str(file_path), lineno))

    return findings

# ----------------------------------------------------------------------
# Main Scanner
# ----------------------------------------------------------------------
def scan_project(exclude_dirs: List[str] = None, strict: bool = False) -> Report:
    if exclude_dirs is None:
        exclude_dirs = ['.venv', 'venv', '__pycache__', '.git', 'node_modules', 'dist', 'build', 'migrations', 'deployment', 'docs', 'tests']
    exclude_set = set(exclude_dirs)

    all_findings = []
    for py_file in PROJECT_ROOT.rglob("*.py"):
        if any(part in exclude_set for part in py_file.parts):
            continue
        if py_file.name.startswith("secret_scanner_checker"):
            continue
        # Skip .env file? File .env dianggap boleh berisi secret (untuk lokal)
        # Kita scan tapi bisa diabaikan dengan --exclude atau kita beri catatan khusus
        findings = check_file(py_file)
        all_findings.extend(findings)

    # Filter: jika strict=False, hanya tampilkan CRITICAL
    if not strict:
        all_findings = [f for f in all_findings if f.severity in ('CRITICAL', 'WARNING')]
    else:
        # Tampilkan semua termasuk INFO
        pass

    # Score: CRITICAL -15, WARNING -5, INFO -1
    score = 100
    for f in all_findings:
        if f.severity == "CRITICAL":
            score -= 15
        elif f.severity == "WARNING":
            score -= 5
        else:
            score -= 1
    score = max(0, score)

    return Report(findings=all_findings, score=score)

# ----------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------
def print_report(report: Report, verbose: bool = False, strict: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}SECRET SCANNER CHECKER REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"\n  Total findings: {len(report.findings)}")
    criticals = sum(1 for f in report.findings if f.severity == "CRITICAL")
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")
    infos = sum(1 for f in report.findings if f.severity == "INFO")
    print(f"  Critical: {c['RED']}{criticals}{c['RESET']}, Warning: {c['YELLOW']}{warnings}{c['RESET']}, Info: {c['CYAN']}{infos}{c['RESET']}")
    print(f"  Score: {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")

    if report.findings:
        print(f"\n{c['RED'] if criticals else c['YELLOW']}Details:{c['RESET']}")
        for f in report.findings[:30]:
            color = c["RED"] if f.severity == "CRITICAL" else c["YELLOW"] if f.severity == "WARNING" else c["CYAN"]
            print(f"  {color}[{f.severity}]{c['RESET']} {f.file}:{f.line}")
            print(f"     {f.message}")
            if verbose:
                print(f"     Snippet: {f.snippet}")
                if f.recommendation:
                    print(f"     {c['CYAN']}💡 {f.recommendation}{c['RESET']}")
        if len(report.findings) > 30:
            print(f"  ... and {len(report.findings)-30} more findings")
    else:
        print(f"\n{c['GREEN']}✅ No secrets found.{c['RESET']}")

def save_json(report: Report, filepath: str):
    data = {
        "findings": [
            {"file": f.file, "line": f.line, "severity": f.severity,
             "message": f.message, "snippet": f.snippet, "recommendation": f.recommendation}
            for f in report.findings
        ],
        "score": report.score,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{c['CYAN']}JSON saved to {filepath}{c['RESET']}")

# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Secret Scanner Checker")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    parser.add_argument("--exclude", default=".venv,venv,__pycache__,node_modules,dist,build,migrations,deployment,docs,tests",
                        help="Folder yang diabaikan (pisahkan dengan koma)")
    parser.add_argument("--strict", action="store_true", help="Tampilkan semua temuan termasuk INFO")
    args = parser.parse_args()

    exclude_dirs = [d.strip() for d in args.exclude.split(",") if d.strip()]
    report = scan_project(exclude_dirs, strict=args.strict)
    print_report(report, verbose=args.verbose, strict=args.strict)
    if args.json:
        save_json(report, args.json)

    criticals = sum(1 for f in report.findings if f.severity == "CRITICAL")
    sys.exit(0 if criticals == 0 else 1)

if __name__ == "__main__":
    main()