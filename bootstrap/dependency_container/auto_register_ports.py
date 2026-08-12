#!/usr/bin/env python3
"""
auto_register_ports.py — Auto-discovery & registration of all ports to IoC container.

Fully dynamic: scans all ports and adapters, matches them intelligently.
If no adapter found, registers a NotImplementedStub that raises clear errors.
"""

import ast
import importlib
import inspect
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# --- Paths ---
# Asumsikan file ini berada di bootstrap/dependency_container/
ROOT = Path(__file__).resolve().parent.parent.parent

PORTS_PRIMARY = ROOT / "ports" / "primary"
PORTS_SECONDARY = ROOT / "ports" / "secondary"
ADAPTERS_IMPL = ROOT / "adapters" / "secondary_impl"
ADAPTERS_API = ROOT / "adapters" / "primary_api"

EXCLUDE_PORTS = {"BasePort", "BaseRepository", "BaseProtocol"}

# ============================================================================
# 1. SCAN PORT CLASSES
# ============================================================================

def get_all_port_classes() -> dict[str, tuple[str, Path]]:
    """Return {port_name: (module_path, file_path)} for all ports."""
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
                        if name.endswith("Port") or name.endswith("Protocol") or name.endswith("Repository"):
                            ports[name] = (module_path, file_path)
            except Exception:
                continue
    return ports

# ============================================================================
# 2. SCAN ADAPTER CLASSES
# ============================================================================

def get_all_adapter_classes() -> dict[str, tuple[str, Path, set[str]]]:
    """Return {class_name: (module_path, file_path, set_of_methods)} for all adapters."""
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
                                methods.add(item.name)
                        adapters[name] = (module_path, file_path, methods)
            except Exception:
                continue
    return adapters

# ============================================================================
# 3. MATCH PORT → ADAPTER (DYNAMIC WITH SUBCLASS CHECK + SCORING)
# ============================================================================

def find_matching_adapter(port_name: str, port_methods: set[str], adapters: dict) -> tuple[str, str] | None:
    """
    Find the best matching adapter for a port using:
    1. Direct subclass check (most reliable)
    2. Name-based scoring with special rules
    """
    base_name = port_name.replace("Port", "").replace("Protocol", "").replace("Repository", "")
    base_lower = base_name.lower()

    # Step 1: Try to find adapter that is a direct subclass of the port
    try:
        port_module_path = None
        for pname, (pmod, _) in get_all_port_classes().items():
            if pname == port_name:
                port_module_path = pmod
                break
        if port_module_path:
            port_mod = importlib.import_module(port_module_path)
            port_class = getattr(port_mod, port_name, None)
            if port_class:
                for adapter_name, (mod_path, _file_path, _methods) in adapters.items():
                    try:
                        impl_mod = importlib.import_module(mod_path)
                        impl_class = getattr(impl_mod, adapter_name, None)
                        if impl_class and issubclass(impl_class, port_class):
                            return mod_path, adapter_name
                    except Exception:
                        continue
    except Exception:
        pass

    # Step 2: If no subclass, use name-based scoring with special rules
    scored = []
    for adapter_name, (mod_path, _file_path, methods) in adapters.items():
        score = 0

        # Special rules for problematic ports
        if port_name == "SalesRepositoryPort" and ("SalesRepositoryAdapter" in adapter_name or "SalesOrderRepository" in adapter_name):
            score += 100
        if port_name == "AMLRepositoryPort" and "AML" in adapter_name and "Repository" in adapter_name:
            score += 100
        if port_name == "AMLRepositoryPortProtocol" and "AML" in adapter_name and "Repository" in adapter_name:
            score += 100

        # General name similarity
        if base_lower in adapter_name.lower():
            score += 50
        if port_name in adapter_name or base_name in adapter_name:
            score += 30

        # Method overlap
        if port_methods:
            overlap = len(port_methods & methods)
            if overlap > 0:
                score += overlap * 5

        # Module path hints
        if "sqlalchemy" in mod_path:
            score += 20
        if "impl" in mod_path or "adapter" in mod_path:
            score += 10

        # Avoid test/mock
        if "test" in mod_path or "mock" in mod_path:
            score -= 50

        if score > 0:
            scored.append((score, mod_path, adapter_name))

    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0]
    return best[1], best[2]

# ============================================================================
# 4. STUB IMPLEMENTATION
# ============================================================================

class _NotImplementedStub:
    def __init__(self, port_name: str):
        self._port_name = port_name

    def __getattribute__(self, name):
        if name.startswith("_"):
            return super().__getattribute__(name)
        raise NotImplementedError(
            f"Adapter for {self._port_name} is not implemented. "
            f"Please create a real adapter in adapters/secondary_impl/"
        )

    async def __call__(self, *args, **kwargs):
        raise NotImplementedError(
            f"Adapter for {self._port_name} is not implemented."
        )

def create_stub(port_name: str):
    return _NotImplementedStub(port_name)

# ============================================================================
# 5. SMART INSTANTIATION
# ============================================================================

def instantiate_adapter(impl_class):
    """
    Try multiple strategies to instantiate the adapter class.
    Does NOT call any async methods — that's the responsibility of the caller.
    """
    # Coba tanpa argumen
    try:
        return impl_class()
    except TypeError:
        pass
    # Coba dengan session=None
    try:
        return impl_class(session=None)
    except Exception:
        pass
    # Coba dengan inspect untuk mengisi parameter yang dibutuhkan dengan None
    try:
        sig = inspect.signature(impl_class.__init__)
        params = {}
        for param_name, param in sig.parameters.items():
            if param_name != 'self' and param.default == inspect.Parameter.empty:
                params[param_name] = None
        return impl_class(**params)
    except Exception:
        pass
    # Terakhir, coba dengan kwargs kosong
    try:
        return impl_class(**{})
    except Exception:
        pass
    raise RuntimeError(f"Cannot instantiate {impl_class.__name__}")

# ============================================================================
# 6. MANUAL LOOKUP FOR CORETAX PORTS
# ============================================================================

def manual_lookup_coretax(port_name: str, adapters: dict, container, port_class, registered, fallback):
    """
    Specialized manual lookup for CoreTaxPort and TaxAuthorityCoretaxPort.
    Returns True if successfully registered, False otherwise.
    """
    # Tentukan pola file yang dicari
    if port_name == "CoreTaxPort":
        # Cari adapter yang tepat: TaxAuthorityCoretaxAdapter (real implementation)
        # Atau setidaknya file yang mengandung "coretax" dan bukan in-memory
        candidates = []
        for adapter_name, (mod_path, _file_path, _methods) in adapters.items():
            if "TaxAuthorityCoretaxAdapter" in adapter_name:
                candidates.append((100, adapter_name, mod_path))
            elif "coretax" in adapter_name.lower() and "InMemory" not in adapter_name:
                candidates.append((50, adapter_name, mod_path))
            elif "core_tax" in str(_file_path).lower():
                candidates.append((30, adapter_name, mod_path))
        # Prioritaskan yang memiliki skor tertinggi
        candidates.sort(key=lambda x: x[0], reverse=True)
    elif port_name == "TaxAuthorityCoretaxPort":
        # Cari TaxAuthorityCoretaxAdapter secara spesifik
        candidates = []
        for adapter_name, (mod_path, _file_path, _methods) in adapters.items():
            if "TaxAuthorityCoretaxAdapter" in adapter_name:
                candidates.append((100, adapter_name, mod_path))
            elif "tax_authority_coretax" in str(_file_path).lower():
                candidates.append((80, adapter_name, mod_path))
        candidates.sort(key=lambda x: x[0], reverse=True)
    else:
        return False

    for _, adapter_name, mod_path in candidates:
        try:
            impl_module = importlib.import_module(mod_path)
            impl_class = getattr(impl_module, adapter_name, None)
            if impl_class is None:
                continue
            instance = instantiate_adapter(impl_class)
            container.register_instance(port_class, instance)
            registered.append(port_name)
            logger.info(f"Registered {port_name} -> {adapter_name}")
            return True
        except Exception as e:
            logger.debug(f"Manual lookup for {port_name} with {adapter_name} failed: {e}")
            continue
    return False

# ============================================================================
# 7. MAIN REGISTRATION
# ============================================================================

def auto_register_ports(container) -> tuple[list[str], list[str]]:
    ports = get_all_port_classes()
    adapters = get_all_adapter_classes()

    registered = []
    fallback = []

    if not ports:
        logger.warning("No ports found")
        return [], []

    logger.info(f"Auto-register: found {len(ports)} port classes, {len(adapters)} adapter classes")

    for port_name, (port_module_path, _port_file_path) in ports.items():
        # Skip if already registered in container
        if hasattr(container, 'has_registration') and container.has_registration(port_name):
            continue

        try:
            port_module = importlib.import_module(port_module_path)
            port_class = getattr(port_module, port_name, None)
            if port_class is None:
                continue
        except Exception:
            continue

        port_methods = set()
        if hasattr(port_class, "__abstractmethods__"):
            port_methods = set(port_class.__abstractmethods__)
        else:
            for method_name in dir(port_class):
                if method_name.startswith("_"):
                    continue
                attr = getattr(port_class, method_name)
                if callable(attr):
                    port_methods.add(method_name)

        # ============================================================
        # SPECIAL HANDLING FOR CORETAX PORTS
        # ============================================================
        if port_name in ("CoreTaxPort", "TaxAuthorityCoretaxPort"):
            if manual_lookup_coretax(port_name, adapters, container, port_class, registered, fallback):
                continue
            else:
                # If manual lookup fails, create stub
                stub = create_stub(port_name)
                container.register_instance(port_class, stub)
                fallback.append(port_name)
                logger.warning(f"Registered {port_name} as STUB (no suitable adapter found)")
                continue

        # ============================================================
        # SPECIAL HANDLING FOR TIMESTAMP NOTARY PORT
        # ============================================================
        if port_name == "TimestampNotaryPort":
            # Cari adapter dengan nama TimestampNotaryImpl atau RFC3161TimestampAdapter
            found = False
            for adapter_name, (mod_path, _file_path, _methods) in adapters.items():
                if "TimestampNotaryImpl" in adapter_name or "RFC3161" in adapter_name:
                    try:
                        impl_module = importlib.import_module(mod_path)
                        impl_class = getattr(impl_module, adapter_name, None)
                        if impl_class is None:
                            continue
                        # JANGAN panggil async method di sini!
                        # Biarkan container/layer yang memanggil initialize() jika diperlukan.
                        instance = instantiate_adapter(impl_class)
                        container.register_instance(port_class, instance)
                        registered.append(port_name)
                        logger.info(f"Registered {port_name} -> {adapter_name}")
                        found = True
                        break
                    except Exception as e:
                        logger.warning(f"Could not instantiate {port_name} with {adapter_name}: {e}")
            if found:
                continue
            else:
                # Jika tidak ditemukan, buat stub
                stub = create_stub(port_name)
                container.register_instance(port_class, stub)
                fallback.append(port_name)
                logger.warning(f"Registered {port_name} as STUB (missing adapter)")
                continue

        # ============================================================
        # NORMAL MATCHING FOR OTHER PORTS
        # ============================================================
        match = find_matching_adapter(port_name, port_methods, adapters)
        if match is not None:
            impl_module_path, impl_class_name = match
            try:
                impl_module = importlib.import_module(impl_module_path)
                impl_class = getattr(impl_module, impl_class_name, None)
                if impl_class is not None:
                    try:
                        instance = instantiate_adapter(impl_class)
                        container.register_instance(port_class, instance)
                        registered.append(port_name)
                        logger.info(f"Registered {port_name} -> {impl_class_name}")
                        continue
                    except Exception as e:
                        logger.warning(f"Could not instantiate {port_name} with {impl_class_name}: {e}")
            except Exception:
                pass

        # If no match or instantiation failed, create stub
        stub = create_stub(port_name)
        container.register_instance(port_class, stub)
        fallback.append(port_name)
        logger.warning(f"Registered {port_name} as STUB (missing adapter)")

    logger.info(f"Auto-register completed: {len(registered)} real, {len(fallback)} stubs")
    return registered, fallback

def register_all_ports(container):
    return auto_register_ports(container)

if __name__ == "__main__":
    # Self-test
    print("Testing auto_register_ports...")
    ports = get_all_port_classes()
    adapters = get_all_adapter_classes()
    print(f"Found {len(ports)} ports, {len(adapters)} adapters")
    for p in list(ports.keys())[:5]:
        print(f"  Port: {p}")
