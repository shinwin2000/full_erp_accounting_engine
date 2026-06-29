#!/usr/bin/env python3
"""
secret_scanner_checker.py - Secret Scanner (Hardcoded Secrets Detector)
=======================================================================
Mendeteksi hardcoded secrets, credentials, token, API key, private key, dll.
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys
from dataclasses import dataclass, field

# ============================================================================
# Warna (untuk output)
# ============================================================================
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

# ============================================================================
# Data Structures
# ============================================================================
@dataclass
class Finding:
    file: str
    line: int
    severity: str          # CRITICAL, WARNING, INFO
    secret_type: str       # e.g. "password", "api_key", "aws_secret"
    value: str
    context: str
    recommendation: str

@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    score: int = 100

# ============================================================================
# Exempt Values (Placeholder / Example)
# ============================================================================
EXEMPT_VALUES = {
    "example", "changeme", "your_", "dummy", "test", "placeholder", "sample", "demo",
    "password", "secret", "token", "api_key", "your-password", "your-secret-key",
    "wrong_password", "minioadmin", "postgres", "root", "admin", "123456", "password123",
    "null", "none", "false", "true", "0", "1", "localhost", "127.0.0.1",
}
EXEMPT_CONTAINS = {"example", "changeme", "your_", "dummy", "test", "placeholder"}

# ============================================================================
# Secret Patterns
# ============================================================================
# Format: (regex, severity, type, recommendation)
SECRET_PATTERNS = [
    # Password
    (re.compile(r'(?i)(password|passwd|pwd|pass)\s*[:=]\s*["\']([^"\']{4,})["\']'), "CRITICAL", "password",
     "Gunakan environment variable atau vault."),
    # API Key
    (re.compile(r'(?i)(api_key|apikey|api-token)\s*[:=]\s*["\']([A-Za-z0-9_\-]{16,})["\']'), "CRITICAL", "api_key",
     "Simpan API key di environment variable."),
    # Token / Bearer
    (re.compile(r'(?i)(token|access_token|refresh_token)\s*[:=]\s*["\']([A-Za-z0-9_\-\.]{20,})["\']'), "CRITICAL", "token",
     "Gunakan environment variable."),
    (re.compile(r'(?i)(bearer|authorization)\s*[:=]\s*["\'](?:Bearer\s+)?([A-Za-z0-9_\-\.]{20,})["\']'), "CRITICAL", "bearer_token",
     "Jangan hardcode bearer token."),
    # JWT Secret
    (re.compile(r'(?i)(jwt_secret|jwt-secret|JWT_SECRET)\s*[:=]\s*["\']([A-Za-z0-9_\-\.]{32,})["\']'), "CRITICAL", "jwt_secret",
     "Gunakan environment variable."),
    # Secret Key (Django, Flask)
    (re.compile(r'(?i)(secret_key|SECRET_KEY)\s*[:=]\s*["\']([A-Za-z0-9@#$!%^&*_\-]{16,})["\']'), "CRITICAL", "secret_key",
     "Pindahkan secret key ke environment variable."),
    # AWS
    (re.compile(r'(?i)(aws_access_key_id|AWS_ACCESS_KEY_ID)\s*[:=]\s*["\'](AKIA[0-9A-Z]{16,})["\']'), "CRITICAL", "aws_access_key",
     "Gunakan IAM role atau environment variable."),
    (re.compile(r'(?i)(aws_secret_access_key|AWS_SECRET_ACCESS_KEY)\s*[:=]\s*["\']([A-Za-z0-9/+=]{16,})["\']'), "CRITICAL", "aws_secret_key",
     "Gunakan IAM role atau environment variable."),
    # Azure
    (re.compile(r'(?i)(azure_connection_string|AZURE_CONNECTION_STRING)\s*[:=]\s*["\'](DefaultEndpointsProtocol=https;AccountName=[^;]+;AccountKey=[^;]+;EndpointSuffix=core.windows.net)["\']'),
     "CRITICAL", "azure_connection_string", "Gunakan Azure Key Vault."),
    (re.compile(r'(?i)(azure_storage_key|AZURE_STORAGE_KEY)\s*[:=]\s*["\']([A-Za-z0-9+/=]{40,})["\']'), "CRITICAL", "azure_storage_key",
     "Gunakan environment variable."),
    # Google
    (re.compile(r'(?i)(google_api_key|GOOGLE_API_KEY)\s*[:=]\s*["\'](AIza[0-9A-Za-z\-_]{35,})["\']'), "CRITICAL", "google_api_key",
     "Gunakan environment variable."),
    # Private key (tanpa group)
    (re.compile(r'-----BEGIN (?:RSA|DSA|EC|OPENSSH) PRIVATE KEY-----'), "CRITICAL", "private_key",
     "Pindahkan private key ke file terpisah."),
    (re.compile(r'-----BEGIN PRIVATE KEY-----'), "CRITICAL", "private_key",
     "Pindahkan private key ke file terpisah."),
    # Database URL
    (re.compile(r'(?i)(database_url|DATABASE_URL|db_url|dsn)\s*[:=]\s*["\'](postgresql|postgres|mysql|mongodb|redis|sqlite|oracle|mssql)://[^:]+:([^@]+)@'),
     "CRITICAL", "database_url", "Gunakan environment variable."),
    # Connection string
    (re.compile(r'(?i)(connection_string|CONNECTION_STRING)\s*[:=]\s*["\']([^"\']+password[^"\']+)["\']'), "CRITICAL", "connection_string",
     "Gunakan environment variable."),
    # FTP
    (re.compile(r'(?i)(ftp_password|sftp_password)\s*[:=]\s*["\']([^"\']{4,})["\']'), "CRITICAL", "ftp_password",
     "Gunakan environment variable."),
    # Credential in URL (username:password@host)
    (re.compile(r'(?i)([a-z0-9_\-]+):([^@\s]{4,})@[a-z0-9\-]+\.[a-z]{2,}'), "WARNING", "credential_in_url",
     "Hindari hardcode credential di URL."),
    # Generic secret
    (re.compile(r'(?i)(secret|credential)\s*[:=]\s*["\']([A-Za-z0-9@#$!%^&*_\-]{20,})["\']'), "WARNING", "generic_secret",
     "Gunakan environment variable."),
]

# Komentar
COMMENT_PATTERNS = [
    (re.compile(r'(?i)(password|passwd|pwd)\s*[:=]\s*[^"\']+'), "WARNING", "password_in_comment",
     "Hapus secret dari komentar."),
    (re.compile(r'(?i)(api_key|apikey|token|secret)\s*[:=]\s*[A-Za-z0-9]{16,}'), "WARNING", "secret_in_comment",
     "Hapus secret dari komentar."),
]

STATUS_CONSTANTS = {
    "FAILURE_WRONG_PASSWORD", "ERROR_", "STATUS_", "SUCCESS_",
    "PASSWORD_RESET", "PASSWORD_CHANGE", "PASSWORD_VALIDATION",
}

# ============================================================================
# Utility
# ============================================================================
def is_exempt_value(value: str) -> bool:
    val = value.lower().strip('"\'')
    if val in EXEMPT_VALUES:
        return True
    for ex in EXEMPT_CONTAINS:
        if ex in val:
            return True
    if len(val) < 4:
        return True
    return False

def extract_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = extract_string(node.left)
        right = extract_string(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        parts = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                parts.append(part.value)
        if parts:
            return ''.join(parts)
    return None

def extract_captured(match: re.Match) -> str | None:
    """Ambil nilai yang ditangkap dengan aman (termasuk pattern tanpa group)."""
    groups = match.groups()
    if not groups:
        return match.group(0)
    for g in reversed(groups):
        if g is not None:
            return g
    return None

# ============================================================================
# AST Visitor
# ============================================================================
class SecretVisitor(ast.NodeVisitor):
    def __init__(self, file_path: str, lines: list[str]):
        self.file = file_path
        self.lines = lines
        self.findings: list[Finding] = []

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            var_name = target.id
            if var_name in STATUS_CONSTANTS:
                continue
            value = extract_string(node.value)
            if value is None or is_exempt_value(value):
                continue
            for pattern, severity, secret_type, recommendation in SECRET_PATTERNS:
                if pattern.search(f"{var_name}={value}"):
                    self._add_finding(node.lineno, severity, secret_type, value, recommendation)
                    break
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        for kw in node.keywords:
            if kw.arg is not None and kw.arg.lower() in {"password", "passwd", "pwd", "api_key", "token", "secret"}:
                value = extract_string(kw.value)
                if value and not is_exempt_value(value):
                    for pattern, severity, secret_type, recommendation in SECRET_PATTERNS:
                        if pattern.search(f"{kw.arg}={value}"):
                            self._add_finding(node.lineno, severity, secret_type, value, recommendation)
                            break
        self.generic_visit(node)

    def _add_finding(self, line: int, severity: str, secret_type: str, value: str, recommendation: str) -> None:
        redacted = value[:20] + "..." if len(value) > 20 else value
        context_line = self.lines[line-1].strip() if line <= len(self.lines) else ""
        self.findings.append(Finding(
            file=self.file,
            line=line,
            severity=severity,
            secret_type=secret_type,
            value=redacted,
            context=context_line[:150],
            recommendation=recommendation,
        ))

# ============================================================================
# Scanner
# ============================================================================
def scan_python_file(file_path: pathlib.Path, root: pathlib.Path) -> list[Finding]:
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        lines = src.splitlines()
    except Exception:
        return []

    findings = []
    # AST
    try:
        tree = ast.parse(src, filename=str(file_path))
        visitor = SecretVisitor(str(file_path.relative_to(root)), lines)
        visitor.visit(tree)
        findings.extend(visitor.findings)
    except SyntaxError:
        pass

    # Regex fallback
    for idx, line in enumerate(lines, 1):
        if line.strip().startswith('#'):
            continue
        for pattern, severity, secret_type, recommendation in SECRET_PATTERNS:
            match = pattern.search(line)
            if match:
                captured = extract_captured(match)
                if captured and not is_exempt_value(captured):
                    redacted = captured[:20] + "..." if len(captured) > 20 else captured
                    findings.append(Finding(
                        file=str(file_path.relative_to(root)),
                        line=idx,
                        severity=severity,
                        secret_type=secret_type,
                        value=redacted,
                        context=line[:150],
                        recommendation=recommendation,
                    ))
                    break

    # Komentar
    for idx, line in enumerate(lines, 1):
        if '#' in line:
            comment = line.split('#', 1)[1].strip()
            if comment:
                for pattern, severity, secret_type, recommendation in COMMENT_PATTERNS:
                    if pattern.search(comment):
                        findings.append(Finding(
                            file=str(file_path.relative_to(root)),
                            line=idx,
                            severity=severity,
                            secret_type=secret_type,
                            value="",
                            context=comment[:100],
                            recommendation=recommendation,
                        ))
                        break
    return findings

def scan_text_file(file_path: pathlib.Path, root: pathlib.Path) -> list[Finding]:
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
    except Exception:
        return []

    findings = []
    for idx, line in enumerate(lines, 1):
        if line.strip().startswith('#'):
            continue
        for pattern, severity, secret_type, recommendation in SECRET_PATTERNS:
            match = pattern.search(line)
            if match:
                captured = extract_captured(match)
                if captured and not is_exempt_value(captured):
                    redacted = captured[:20] + "..." if len(captured) > 20 else captured
                    findings.append(Finding(
                        file=str(file_path.relative_to(root)),
                        line=idx,
                        severity=severity,
                        secret_type=secret_type,
                        value=redacted,
                        context=line[:150],
                        recommendation=recommendation,
                    ))
                    break
    return findings

def scan_file(file_path: pathlib.Path, root: pathlib.Path) -> list[Finding]:
    if file_path.suffix.lower() == ".py":
        return scan_python_file(file_path, root)
    else:
        return scan_text_file(file_path, root)

# ============================================================================
# Project Scanner
# ============================================================================
def scan_project(target_dir: pathlib.Path, exclude_dirs: list[str] = None, strict: bool = False) -> Report:
    if exclude_dirs is None:
        exclude_dirs = [".venv", "venv", "__pycache__", ".git", "node_modules", "dist", "build",
                        "migrations", "deployment", "docs", "tests", "test"]
    exclude_set = set(exclude_dirs)

    extensions = {".py", ".env", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".txt", ".sh", ".bash", ".ps1"}

    all_findings = []
    file_count = 0
    for file_path in target_dir.rglob("*"):
        if file_path.is_dir():
            continue
        if any(part in exclude_set for part in file_path.parts):
            continue
        if file_path.suffix.lower() not in extensions:
            continue
        if file_path.name.startswith("secret_scanner_checker"):
            continue
        file_count += 1
        findings = scan_file(file_path, target_dir)
        all_findings.extend(findings)

    print(f"  Scanned {file_count} files.")

    if not strict:
        all_findings = [f for f in all_findings if f.severity in ("CRITICAL", "WARNING")]

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

# ============================================================================
# Output
# ============================================================================
def print_report(report: Report, verbose: bool = False) -> None:
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}SECRET SCANNER CHECKER REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"\n  Total findings: {len(report.findings)}")
    criticals = sum(1 for f in report.findings if f.severity == "CRITICAL")
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")
    infos = sum(1 for f in report.findings if f.severity == "INFO")
    print(f"  Critical: {c['RED']}{criticals}{c['RESET']}, Warning: {c['YELLOW']}{warnings}{c['RESET']}, Info: {c['CYAN']}{infos}{c['RESET']}")
    print(f"  Security Score: {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")

    if report.findings:
        print(f"\n{c['RED'] if criticals else c['YELLOW']}Details:{c['RESET']}")
        for f in report.findings[:30]:
            color = c["RED"] if f.severity == "CRITICAL" else c["YELLOW"] if f.severity == "WARNING" else c["CYAN"]
            print(f"  {color}[{f.severity}]{c['RESET']} {f.file}:{f.line}  ({f.secret_type})")
            print(f"     {f.value}")
            if verbose:
                print(f"     Context: {f.context}")
                if f.recommendation:
                    print(f"     {c['CYAN']}💡 {f.recommendation}{c['RESET']}")
        if len(report.findings) > 30:
            print(f"  ... and {len(report.findings)-30} more findings")
    else:
        print(f"\n{c['GREEN']}✅ No hardcoded secrets detected.{c['RESET']}")

def save_json(report: Report, filepath: str) -> None:
    data = {
        "findings": [
            {
                "file": f.file,
                "line": f.line,
                "severity": f.severity,
                "type": f.secret_type,
                "value": f.value,
                "context": f.context,
                "recommendation": f.recommendation,
            }
            for f in report.findings
        ],
        "score": report.score,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{COLOR['CYAN']}JSON report saved to {filepath}{COLOR['RESET']}")

# ============================================================================
# CLI
# ============================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="Secret Scanner Checker")
    parser.add_argument("--path", default=".", help="Direktori target (default: current directory)")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail temuan")
    parser.add_argument("--json", metavar="FILE", help="Simpan laporan dalam JSON")
    parser.add_argument("--exclude", default=".venv,venv,__pycache__,node_modules,dist,build,migrations,deployment,docs,tests,test",
                        help="Folder yang diabaikan (pisahkan dengan koma)")
    parser.add_argument("--strict", action="store_true", help="Tampilkan semua temuan termasuk INFO")
    args = parser.parse_args()

    target_dir = pathlib.Path(args.path).resolve()
    if not target_dir.is_dir():
        print(f"Error: {target_dir} is not a directory.")
        sys.exit(1)

    exclude_dirs = [d.strip() for d in args.exclude.split(",") if d.strip()]
    print(f"Scanning directory: {target_dir}")
    report = scan_project(target_dir, exclude_dirs, strict=args.strict)
    print_report(report, verbose=args.verbose)
    if args.json:
        save_json(report, args.json)

    criticals = sum(1 for f in report.findings if f.severity == "CRITICAL")
    sys.exit(1 if criticals > 0 else 0)

if __name__ == "__main__":
    main()