#!/usr/bin/env python3
"""
Script to fix port-adapter contract violations by adding missing methods.
"""
import ast
import os
from pathlib import Path
from typing import Dict, List, Set, Tuple

ROOT = Path("/workspace")
PORTS_DIR = ROOT / "ports" / "primary"
ADAPTERS_DIR = ROOT / "adapters" / "secondary_impl"

def get_ast_tree(filepath: Path):
    """Parse Python file to AST."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return ast.parse(f.read(), filename=str(filepath))
    except Exception as e:
        print(f"Error parsing {filepath}: {e}")
        return None

def extract_class_methods(tree: ast.AST, class_name: str) -> Set[str]:
    """Extract all method names from a class."""
    methods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.add(item.name)
    return methods

def extract_port_classes(filepath: Path) -> Dict[str, Set[str]]:
    """Extract all port classes and their methods from a port file."""
    tree = get_ast_tree(filepath)
    if not tree:
        return {}
    
    port_classes = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Check if it's a port class (contains Port or Repository in name)
            if "Port" in node.name or ("Repository" in node.name and "Port" in node.name):
                methods = set()
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not item.name.startswith('_') or item.name in ['__init__']:
                            methods.add(item.name)
                        elif item.name.startswith('_'):
                            # Include private methods that are defined in the port
                            methods.add(item.name)
                port_classes[node.name] = methods
    return port_classes

def find_matching_adapter(port_stem: str, adapter_files: Dict[str, Path]) -> Tuple[str, Path]:
    """Find matching adapter file for a port."""
    base = port_stem.replace("_port", "").replace("_repository", "")
    
    # Try different naming patterns
    patterns = [
        f"sqlalchemy_{base}_impl",
        f"sqlalchemy_{base}_repository_impl",
        f"{base}_impl",
        f"{base}_repository_impl",
    ]
    
    for pattern in patterns:
        if pattern in adapter_files:
            return pattern, adapter_files[pattern]
    
    # Fuzzy match
    for adapter_stem, adapter_path in adapter_files.items():
        if base in adapter_stem or port_stem.replace("_port", "") in adapter_stem:
            return adapter_stem, adapter_path
    
    return None, None

def generate_stub_method(method_name: str, is_async: bool = True) -> str:
    """Generate a stub method implementation."""
    indent = "    "
    if is_async:
        return f"""{indent}async def {method_name}(self, *args, **kwargs):
{indent}    \"\"\"Stub implementation - TODO: Implement properly.\"\"\"
{indent}    raise NotImplementedError(\"Method {method_name} not yet implemented\")
"""
    else:
        return f"""{indent}def {method_name}(self, *args, **kwargs):
{indent}    \"\"\"Stub implementation - TODO: Implement properly.\"\"\"
{indent}    raise NotImplementedError("Method {method_name} not yet implemented")
"""

def add_missing_methods_to_file(adapter_path: Path, missing_methods: Set[str], class_name: str):
    """Add missing methods to an adapter file."""
    with open(adapter_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the class definition and its last line
    lines = content.split('\n')
    class_start = -1
    class_end = -1
    indent_level = 0
    
    for i, line in enumerate(lines):
        if f"class {class_name}" in line:
            class_start = i
            # Find the indentation of the class
            indent_level = len(line) - len(line.lstrip())
        elif class_start >= 0 and line.strip() and not line.startswith(' ' * (indent_level + 1)) and not line.startswith('\t'):
            if class_end == -1:
                class_end = i
                break
    
    if class_end == -1:
        class_end = len(lines)
    
    # Generate stub methods
    stub_methods = []
    for method in sorted(missing_methods):
        is_async = any(keyword in content for keyword in ['async def', 'Async'])
        stub = generate_stub_method(method, is_async=True)  # Assume async for repository methods
        stub_methods.append(stub)
    
    # Insert before the end of the class
    insert_pos = class_end
    new_content = lines[:insert_pos] + [''] + stub_methods + [''] + lines[insert_pos:]
    
    with open(adapter_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_content))
    
    return len(missing_methods)

def main():
    print("Scanning ports and adapters...")
    
    # Collect all adapter files
    adapter_files = {}
    for py_file in ADAPTERS_DIR.glob("*.py"):
        if py_file.name != "__init__.py":
            adapter_files[py_file.stem] = py_file
    
    # Collect all port files and their classes
    port_files = {}
    for py_file in PORTS_DIR.glob("*.py"):
        if py_file.name != "__init__.py":
            port_classes = extract_port_classes(py_file)
            if port_classes:
                port_files[py_file.stem] = (py_file, port_classes)
    
    print(f"Found {len(port_files)} port files and {len(adapter_files)} adapter files")
    
    total_missing = 0
    fixed_count = 0
    
    for port_stem, (port_path, port_classes) in port_files.items():
        adapter_stem, adapter_path = find_matching_adapter(port_stem, adapter_files)
        
        if not adapter_path:
            print(f"⚠ No adapter found for port: {port_stem}")
            continue
        
        # Get existing methods in adapter
        adapter_tree = get_ast_tree(adapter_path)
        if not adapter_tree:
            continue
        
        # Find the main class in adapter
        adapter_class_name = None
        for node in ast.walk(adapter_tree):
            if isinstance(node, ast.ClassDef):
                if "Impl" in node.name or "Adapter" in node.name or "Repository" in node.name:
                    adapter_class_name = node.name
                    break
        
        if not adapter_class_name:
            print(f"⚠ No suitable class found in {adapter_path}")
            continue
        
        existing_methods = extract_class_methods(adapter_tree, adapter_class_name)
        
        # Check each port class
        for port_class_name, port_methods in port_classes.items():
            missing = port_methods - existing_methods
            
            # Filter out special methods that might not need implementation
            missing = {m for m in missing if not m.startswith('__')}
            
            if missing:
                print(f"\n📝 {port_class_name} -> {adapter_class_name}:")
                print(f"   Missing {len(missing)} methods: {sorted(missing)[:10]}{'...' if len(missing) > 10 else ''}")
                total_missing += len(missing)
                
                # Uncomment below to actually add stubs (be careful!)
                # fixed = add_missing_methods_to_file(adapter_path, missing, adapter_class_name)
                # fixed_count += fixed
                # print(f"   ✓ Added {fixed} stub methods")
    
    print(f"\n{'='*60}")
    print(f"Total missing methods: {total_missing}")
    print(f"Fixed methods: {fixed_count}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
