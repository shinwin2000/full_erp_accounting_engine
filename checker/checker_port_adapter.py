#!/usr/bin/env python3
"""
PORT-ADAPTER ARCHITECTURE VERIFIER - V9.1 (ENCODING FIX)
Menangani berbagai encoding dan memberikan laporan lengkap.
"""

import ast
import logging
import sys
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# KONFIGURASI
# ============================================================================
ROOT = Path(__file__).resolve().parent.parent  # karena checker ada di subfolder
if not (ROOT / "ports").exists():
    ROOT = Path(__file__).resolve().parent

PORTS_DIRS = [
    ROOT / "ports" / "primary",
    ROOT / "ports" / "secondary",
]
ADAPTERS_DIRS = [
    ROOT / "adapters" / "secondary_impl",
    ROOT / "adapters" / "primary_impl",
    ROOT / "infrastructure",
]

EXCLUDE_PORTS = {"BasePort", "BaseRepository", "BaseProtocol", "Port", "Repository", "Protocol"}
EXCLUDE_ADAPTERS = {"Error", "Exception", "Factory", "Dummy", "Fallback", "Mock", "Stub"}

# ============================================================================
# ENCODING HELPER
# ============================================================================
def read_file_with_fallback(file_path: Path) -> str | None:
    """Read file with multiple encoding attempts."""
    encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252', 'windows-1252']
    for enc in encodings:
        try:
            return file_path.read_text(encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    # Ultimate fallback: ignore errors
    try:
        return file_path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return None

# ============================================================================
# DATA STRUCTURES
# ============================================================================
class ClassInfo:
    __slots__ = ("bases", "file", "layer", "methods", "name", "resolved_methods")

    def __init__(self, name: str, file: Path, layer: str, bases: set[str], methods: set[str]):
        self.name = name
        self.file = file
        self.layer = layer  # "PORT" or "ADAPTER"
        self.bases = bases
        self.methods = methods
        self.resolved_methods: set[str] = set()

    def __repr__(self):
        return f"<{self.layer} {self.name} from {self.file.name}>"


class Registry:
    def __init__(self):
        self.classes: dict[str, ClassInfo] = {}
        self.failed_files: list[Path] = []

    def add(self, info: ClassInfo):
        self.classes[info.name] = info

    def get(self, name: str) -> ClassInfo | None:
        return self.classes.get(name)

    def resolve_inheritance(self):
        """Resolve all methods from base classes."""
        visited: set[str] = set()

        def _resolve(cls_name: str):
            if cls_name in visited:
                return
            visited.add(cls_name)
            info = self.get(cls_name)
            if not info:
                return
            if info.resolved_methods:
                return
            # Start with own methods
            info.resolved_methods = set(info.methods)
            for base in info.bases:
                _resolve(base)
                base_info = self.get(base)
                if base_info:
                    info.resolved_methods.update(base_info.resolved_methods)

        for cls_name in list(self.classes.keys()):
            _resolve(cls_name)

# ============================================================================
# PARSER
# ============================================================================
def parse_file(file_path: Path, layer: str, registry: Registry) -> None:
    """Parse a Python file and register classes."""
    content = read_file_with_fallback(file_path)
    if content is None:
        logger.error(f"Failed to read {file_path} (all encodings failed)")
        registry.failed_files.append(file_path)
        return

    try:
        tree = ast.parse(content, filename=str(file_path))
    except SyntaxError as e:
        logger.error(f"Syntax error in {file_path}: {e}")
        registry.failed_files.append(file_path)
        return
    except Exception as e:
        logger.error(f"Unexpected error parsing {file_path}: {e}")
        registry.failed_files.append(file_path)
        return

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        name = node.name
        if name.startswith("_"):
            continue

        # Skip excluded names
        if layer == "PORT" and name in EXCLUDE_PORTS:
            continue
        if layer == "ADAPTER" and any(name.endswith(s) for s in EXCLUDE_ADAPTERS):
            continue

        # Ports must end with Port or Protocol
        if layer == "PORT" and not (name.endswith("Port") or name.endswith("Protocol")):
            continue

        # Collect base class names
        bases: set[str] = set()
        for b in node.bases:
            if isinstance(b, ast.Name):
                bases.add(b.id)
            elif isinstance(b, ast.Attribute):
                bases.add(b.attr)
            else:
                try:
                    bases.add(ast.unparse(b))
                except Exception:
                    pass

        # Collect public methods (not starting with _)
        methods: set[str] = set()
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not item.name.startswith("_"):
                    methods.add(item.name)

        info = ClassInfo(
            name=name,
            file=file_path,
            layer=layer,
            bases=bases,
            methods=methods,
        )
        registry.add(info)
        logger.debug(f"Registered {info}")

# ============================================================================
# NORMALIZATION (for fallback matching)
# ============================================================================
def normalize_name(name: str) -> str:
    """Normalize class name to base token."""
    # Remove common prefixes/suffixes
    for prefix in ("SQLAlchemy", "InMemory", "Postgres", "AsyncPG", "Kafka", "Redis", "MinIO", "S3"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    for suffix in ("Port", "Protocol", "Adapter", "Impl", "Repository", "Store", "Cache"):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break
    # Convert CamelCase to lowercase with underscores
    import re
    name = re.sub(r'(?<=[a-z0-9])([A-Z])', r'_\1', name).lower()
    return name

# ============================================================================
# MATCHING ENGINE
# ============================================================================
def match_ports_to_adapters(registry: Registry) -> dict[str, tuple[str, set[str]] | None]:
    """
    Returns dict: port_name -> (adapter_name, missing_methods) or None.
    """
    ports = {k: v for k, v in registry.classes.items() if v.layer == "PORT"}
    adapters = {k: v for k, v in registry.classes.items() if v.layer == "ADAPTER"}

    result: dict[str, tuple[str, set[str]] | None] = {}

    for port_name, port_info in ports.items():
        best_adapter: ClassInfo | None = None
        best_score = -1
        best_missing: set[str] = set()

        for adp_name, adp_info in adapters.items():
            # Primary: explicit inheritance
            if port_name in adp_info.bases:
                score = 1000
            else:
                # Secondary: name similarity
                norm_port = normalize_name(port_name)
                norm_adp = normalize_name(adp_name)
                if norm_port == norm_adp:
                    score = 500
                else:
                    # partial match
                    if norm_port in norm_adp or norm_adp in norm_port:
                        score = 300
                    else:
                        continue

            # Calculate method coverage
            port_methods = port_info.resolved_methods
            adp_methods = adp_info.resolved_methods

            if port_methods:
                covered = len(port_methods & adp_methods)
                missing = port_methods - adp_methods
                score += covered * 30
                score -= len(missing) * 20
                # penalty for extra methods (optional)
                extra = adp_methods - port_methods
                if extra:
                    score -= len(extra) * 5
            else:
                # marker interface
                score += 100

            # Prefer adapters with higher coverage
            if score > best_score:
                best_score = score
                best_adapter = adp_info
                best_missing = missing if port_methods else set()

        # Threshold for valid match
        if best_adapter and best_score >= 200:
            result[port_name] = (best_adapter.name, best_missing)
        else:
            result[port_name] = None

    return result

# ============================================================================
# MAIN
# ============================================================================
def main():
    print("=" * 100)
    print(" ⚡ SOVEREIGN ARCH-ENGINE COMPILER & COMPLIANCE DASHBOARD V9.1 ⚡")
    print("=" * 100)
    print(f"📂 Project Root : {ROOT}")

    registry = Registry()

    # Parse ports
    for port_dir in PORTS_DIRS:
        if port_dir.exists():
            logger.info(f"Scanning ports: {port_dir}")
            for file_path in port_dir.rglob("*.py"):
                if file_path.name == "__init__.py" or "__pycache__" in str(file_path):
                    continue
                parse_file(file_path, "PORT", registry)
        else:
            logger.warning(f"Port directory not found: {port_dir}")

    # Parse adapters
    for adapter_dir in ADAPTERS_DIRS:
        if adapter_dir.exists():
            logger.info(f"Scanning adapters: {adapter_dir}")
            for file_path in adapter_dir.rglob("*.py"):
                if file_path.name == "__init__.py" or "__pycache__" in str(file_path):
                    continue
                parse_file(file_path, "ADAPTER", registry)
        else:
            logger.warning(f"Adapter directory not found: {adapter_dir}")

    # Resolve inheritance
    registry.resolve_inheritance()

    # Match
    matches = match_ports_to_adapters(registry)

    # Statistics
    total = len(matches)
    passed = sum(1 for v in matches.values() if v is not None and not v[1])
    partial = sum(1 for v in matches.values() if v is not None and v[1])
    missing = sum(1 for v in matches.values() if v is None)

    print("\n📊 METRICS SUMMARY:")
    print(f"   ▪️ Total Port Interface : {total}")
    print(f"   🟩 REAL (lengkap)      : {passed}")
    print(f"   🟨 PARTIAL (kurang)    : {partial}")
    print(f"   🟥 MISSING (tak ada)   : {missing}")
    print(f"   📈 Compliance Rate     : {(passed/total*100):.1f}%")
    if registry.failed_files:
        print(f"   ⚠️  Files failed to parse: {len(registry.failed_files)}")
        for f in registry.failed_files:
            print(f"      - {f.relative_to(ROOT)}")
    print("-" * 100)

    # Detail report
    for port_name in sorted(matches.keys()):
        result = matches[port_name]
        port_info = registry.get(port_name)
        if not port_info:
            continue

        if result is None:
            print(f"❌ {port_name} → TIDAK ADA ADAPTER")
            print(f"   📍 File: {port_info.file.relative_to(ROOT)}")
        else:
            adp_name, missing_methods = result
            if missing_methods:
                print(f"⚠️  {port_name} → PARTIAL (Adapter: {adp_name})")
                print(f"   📍 File Port: {port_info.file.relative_to(ROOT)}")
                adp_info = registry.get(adp_name)
                if adp_info:
                    print(f"   📍 File Adapter: {adp_info.file.relative_to(ROOT)}")
                print(f"   ❌ Missing: {', '.join(sorted(missing_methods))}")
            else:
                print(f"✅ {port_name} → {adp_name}")
                print(f"   📍 File Port: {port_info.file.relative_to(ROOT)}")
                adp_info = registry.get(adp_name)
                if adp_info:
                    print(f"   📍 File Adapter: {adp_info.file.relative_to(ROOT)}")
        print("-" * 100)

    # Exit code
    if missing > 0 or partial > 0:
        print("🛑 AUDIT STATUS: GAGAL. Selesaikan port yang PARTIAL/MISSING.")
        sys.exit(1)
    else:
        print("🎉 EXCELLENT: 100% Kepatuhan Arsitektur Tercapai. Engine Siap Audit.")
        if registry.failed_files:
            print("⚠️  Namun ada file yang gagal dibaca. Perbaiki encoding untuk audit sempurna.")
        sys.exit(0)


if __name__ == "__main__":
    main()
