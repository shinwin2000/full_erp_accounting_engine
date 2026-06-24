#!/usr/bin/env python3
"""
auto_register_ports.py — Auto-discovery & registration of all ports to IoC container.
This script scans ports/primary and ports/secondary for port interfaces,
finds their implementations in adapters/secondary_impl, and registers them.
If no implementation is found, it creates an in-memory fallback.

Usage:
    from auto_register_ports import register_all_ports
    register_all_ports(container)
"""

import ast
import importlib
import logging
import sys
from pathlib import Path
from typing import Dict, Set, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Calculate project root
# Assuming this file is at: <project_root>/bootstrap/dependency_container/auto_register_ports.py
ROOT = Path(__file__).resolve().parent.parent.parent

# Directories to scan
PORTS_PRIMARY = ROOT / "ports" / "primary"
PORTS_SECONDARY = ROOT / "ports" / "secondary"
ADAPTERS_IMPL = ROOT / "adapters" / "secondary_impl"

# Optional: exclude certain ports from auto-registration (e.g., base classes)
EXCLUDE_PORTS = {"BasePort", "BaseRepository", "BaseProtocol"}


def get_all_port_classes() -> Dict[str, Tuple[str, Path]]:
    """
    Scan ports/primary and ports/secondary to find all port classes.
    Returns: dict {class_name: (module_path, file_path)}
    """
    ports = {}

    for base_dir in [PORTS_PRIMARY, PORTS_SECONDARY]:
        if not base_dir.exists():
            logger.warning(f"Directory not found: {base_dir}")
            continue

        for file_path in base_dir.glob("*.py"):
            if file_path.name == "__init__.py":
                continue

            # Build module import path: relative to project root, no .py suffix, replace slashes with dots
            module_path = str(file_path.relative_to(ROOT).with_suffix("")).replace("\\", ".").replace("/", ".")

            try:
                tree = ast.parse(file_path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        name = node.name
                        if name in EXCLUDE_PORTS:
                            continue
                        # Only consider classes ending with Port, Protocol, or Repository
                        if name.endswith("Port") or name.endswith("Protocol") or name.endswith("Repository"):
                            ports[name] = (module_path, file_path)
            except Exception as e:
                logger.warning(f"Error parsing {file_path}: {e}")

    return ports


def find_implementation(port_name: str) -> Optional[Tuple[str, str]]:
    """
    Find an implementation for a port in adapters/secondary_impl.
    Returns: (module_path, class_name) or None
    """
    if not ADAPTERS_IMPL.exists():
        return None

    # Build candidate module names based on port name
    base_name = port_name.replace("Port", "").replace("Protocol", "").replace("Repository", "")
    base_lower = base_name.lower()

    candidates = [
        f"sqlalchemy_{base_lower}_repository_impl",
        f"sqlalchemy_{base_lower}_impl",
        f"{base_lower}_repository_impl",
        f"{base_lower}_impl",
        f"sqlalchemy_{base_lower}_adapter",
        f"{base_lower}_adapter",
    ]

    # Also try with "repository" in the name if port ends with Repository
    if port_name.endswith("Repository") and "repository" not in base_lower:
        candidates.append(f"sqlalchemy_{base_lower}_repository_impl")
        candidates.append(f"{base_lower}_repository_impl")

    for impl_file in ADAPTERS_IMPL.glob("*.py"):
        if impl_file.name == "__init__.py":
            continue
        stem = impl_file.stem
        # Check if stem matches any candidate
        for cand in candidates:
            if cand in stem or stem in cand:
                module_path = f"adapters.secondary_impl.{stem}"
                # Scan the file for classes that implement the port
                try:
                    tree = ast.parse(impl_file.read_text(encoding="utf-8"))
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef):
                            # Check inheritance (base classes)
                            for base in node.bases:
                                if isinstance(base, ast.Name) and base.id == port_name:
                                    return module_path, node.name
                            # Check if class name contains the base_name
                            if base_name.lower() in node.name.lower():
                                return module_path, node.name
                except Exception:
                    continue

    return None


def create_in_memory_fallback(port_name: str, base_name: str) -> Tuple[str, type]:
    """
    Generate an in-memory fallback class for a port.
    Returns: (class_name, class_object)
    """
    class_name = f"_InMemory{base_name}Impl"

    # Build method stubs dynamically based on port name heuristics
    methods = [
        "    async def save(self, entity): ...",
        "    async def find_by_id(self, id): ...",
        "    async def find_all(self, limit=100, offset=0): ...",
    ]

    # Add specialized methods based on port name patterns
    if "AR" in port_name or "AP" in port_name:
        methods.append("    async def save_invoice(self, invoice): ...")
        methods.append("    async def find_invoice_by_id(self, invoice_id): ...")
    if "Inventory" in port_name:
        methods.append("    async def save_item(self, item): ...")
        methods.append("    async def find_item_by_id(self, item_id): ...")
        methods.append("    async def adjust_stock(self, item_id, quantity): ...")
    if "LegalEntity" in port_name:
        methods.append("    async def get_by_id(self, entity_id): ...")
    if "SystemSetting" in port_name:
        methods.append("    async def get_setting(self, key): ...")
        methods.append("    async def set_setting(self, key, value): ...")
    if "TaxTransaction" in port_name:
        methods.append("    async def save_transaction(self, tx): ...")
        methods.append("    async def find_by_id(self, tx_id): ...")
    if "TimestampNotary" in port_name:
        methods.append("    async def notarize(self, data): ...")
        methods.append("    async def verify(self, notarized_data): ...")
    if "EncryptionKeyVault" in port_name:
        methods.append("    async def get_key(self, key_id): ...")
        methods.append("    async def rotate_key(self, key_id): ...")
    if "Customer" in port_name or "Supplier" in port_name:
        methods.append("    async def find_by_code(self, code): ...")
    if "Employee" in port_name:
        methods.append("    async def find_by_nik(self, nik): ...")

    class_def = f"""
class {class_name}:
    \"\"\"In-memory fallback for {port_name}.\"\"\"
    def __init__(self):
        self._data = {{}}
        self._counter = 0

{chr(10).join(methods)}
"""
    # Execute class definition in a safe namespace
    ns = {}
    exec(class_def, globals(), ns)
    impl_class = ns.get(class_name)
    if not impl_class:
        raise RuntimeError(f"Failed to create fallback class {class_name}")
    return class_name, impl_class


class _InMemoryGenericRepository:
    """Generic in-memory repository fallback used when specific fallback cannot be created."""
    def __init__(self):
        self._data = {}
        self._counter = 0

    async def save(self, entity):
        if hasattr(entity, "id"):
            self._data[entity.id] = entity
        else:
            self._counter += 1
            setattr(entity, "id", self._counter)
            self._data[entity.id] = entity

    async def find_by_id(self, id):
        return self._data.get(id)

    async def find_all(self, limit=100, offset=0):
        return list(self._data.values())[offset:offset+limit]


def auto_register_ports(container) -> Tuple[List[str], List[str]]:
    """
    Auto-detect all ports, find implementations, and register them to container.
    Returns: (registered_ports, fallback_ports)
    """
    ports = get_all_port_classes()
    registered = []
    fallback = []

    logger.info(f"Auto-register: found {len(ports)} port classes in filesystem")

    for port_name, (module_path, file_path) in ports.items():
        # Skip if already registered (container might already have some explicit registrations)
        # We'll check if container already has registration for this interface
        if hasattr(container, 'has_registration') and container.has_registration(port_name):
            logger.debug(f"Port {port_name} already registered, skipping")
            continue

        # Import port interface
        try:
            port_module = importlib.import_module(module_path)
            port_class = getattr(port_module, port_name, None)
            if port_class is None:
                logger.warning(f"Port {port_name} not found in {module_path}, skipping")
                continue
        except Exception as e:
            logger.warning(f"Could not import {module_path}: {e}")
            continue

        # Find implementation
        impl = find_implementation(port_name)
        if impl is None:
            # No implementation found, create in-memory fallback
            base_name = port_name.replace("Port", "").replace("Protocol", "").replace("Repository", "")
            try:
                _, impl_class = create_in_memory_fallback(port_name, base_name)
                container.register_instance(port_class, impl_class())
                fallback.append(port_name)
                logger.info(f"Registered {port_name} (in-memory fallback)")
            except Exception as e:
                logger.warning(f"Failed to create fallback for {port_name}: {e}, using generic repository")
                container.register_instance(port_class, _InMemoryGenericRepository())
                fallback.append(port_name)
            continue

        # Real implementation found
        impl_module_path, impl_class_name = impl
        try:
            impl_module = importlib.import_module(impl_module_path)
            impl_class = getattr(impl_module, impl_class_name, None)
            if impl_class is None:
                logger.warning(f"Class {impl_class_name} not found in {impl_module_path}")
                # Use fallback
                base_name = port_name.replace("Port", "").replace("Protocol", "").replace("Repository", "")
                try:
                    _, fallback_class = create_in_memory_fallback(port_name, base_name)
                    container.register_instance(port_class, fallback_class())
                    fallback.append(port_name)
                    logger.info(f"Registered {port_name} (fallback due to missing class)")
                except Exception:
                    container.register_instance(port_class, _InMemoryGenericRepository())
                    fallback.append(port_name)
                continue

            # Instantiate the adapter
            try:
                instance = impl_class()
                container.register_instance(port_class, instance)
                registered.append(port_name)
                logger.info(f"Registered {port_name} -> {impl_class_name}")
            except Exception as e:
                logger.warning(f"Could not instantiate {port_name} ({impl_class_name}): {e}, using fallback")
                base_name = port_name.replace("Port", "").replace("Protocol", "").replace("Repository", "")
                try:
                    _, fallback_class = create_in_memory_fallback(port_name, base_name)
                    container.register_instance(port_class, fallback_class())
                    fallback.append(port_name)
                except Exception:
                    container.register_instance(port_class, _InMemoryGenericRepository())
                    fallback.append(port_name)

        except Exception as e:
            logger.warning(f"Error registering {port_name}: {e}, using fallback")
            base_name = port_name.replace("Port", "").replace("Protocol", "").replace("Repository", "")
            try:
                _, fallback_class = create_in_memory_fallback(port_name, base_name)
                container.register_instance(port_class, fallback_class())
                fallback.append(port_name)
            except Exception:
                container.register_instance(port_class, _InMemoryGenericRepository())
                fallback.append(port_name)

    logger.info(f"Auto-register completed: {len(registered)} ports with real impl, {len(fallback)} using fallback")
    return registered, fallback


def register_all_ports(container):
    """Public interface for ioc_container.py."""
    return auto_register_ports(container)


if __name__ == "__main__":
    # Quick test (requires container import)
    try:
        from bootstrap.dependency_container.ioc_container import get_container
        container = get_container()
        registered, fallback = register_all_ports(container)
        print(f"Registered {len(registered)} ports, fallback for {len(fallback)} ports")
        print("Registered:", registered)
        print("Fallback:", fallback)
    except ImportError as e:
        print(f"Could not import container: {e}")
        sys.exit(1)