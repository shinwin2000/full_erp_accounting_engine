#!/usr/bin/env python3
"""
Module: dependency_graph_validator.py
Layer: Bootstrap (Dependency Container)
Responsibility: Memvalidasi dependency graph untuk mendeteksi circular dependencies
               dan memastikan semua dependensi dapat di-resolve.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any

from bootstrap.dependency_container.ioc_container import IoCContainer, get_container

logger = logging.getLogger(__name__)


class DependencyGraphError(Exception):
    """Base exception untuk dependency graph."""
    pass


class CircularDependencyError(DependencyGraphError):
    """Circular dependency terdeteksi."""

    def __init__(self, cycle: list[str]):
        self.cycle = cycle
        super().__init__(f"Circular dependency detected: {' -> '.join(cycle)}")


class DependencyGraphValidator:
    """
    Validator untuk dependency graph.

    Method Standards:
    - build_graph() - Membangun graph
    - detect_circular_dependencies() - Mendeteksi circular
    - validate_all_dependencies() - Validasi semua dependensi
    - analyze_depth() - Analisis kedalaman
    - get_health_report() - Laporan kesehatan
    - print_report() - Cetak laporan
    - reset() - Reset graph
    - get_node_count() - Jumlah node
    - get_edges() - Mendapatkan edge
    """

    def __init__(self, container: IoCContainer | None = None):
        self._container = container or get_container()
        self._graph: dict[str, set[str]] = {}
        self._visited: set[str] = set()
        self._recursion_stack: set[str] = set()
        self._logger = logging.getLogger(f"{__name__}.DependencyGraphValidator")

    def _get_class_name(self, cls: type) -> str:
        """Get fully qualified class name."""
        return f"{cls.__module__}.{cls.__name__}"

    def _extract_dependencies(self, cls: type) -> list[type]:
        """Extract dependencies from class constructor."""
        dependencies = []
        try:
            sig = inspect.signature(cls.__init__)
            for name, param in sig.parameters.items():
                if name == "self":
                    continue
                param_type = param.annotation
                if param_type != inspect.Parameter.empty and isinstance(param_type, type):
                    dependencies.append(param_type)
        except Exception as e:
            self._logger.warning(f"Could not extract dependencies from {cls.__name__}: {e}")
        return dependencies

    def build_graph(self) -> None:
        """Build dependency graph from registered classes."""
        self._graph.clear()
        registered_types = self._container.get_registered_types()

        for interface in registered_types:
            interface_name = self._get_class_name(interface)
            self._graph[interface_name] = set()

            try:
                impl = self._container._registrations.get(interface)
                if impl and impl.implementation:
                    impl_class = impl.implementation
                    dependencies = self._extract_dependencies(impl_class)
                    for dep in dependencies:
                        dep_name = self._get_class_name(dep)
                        self._graph[interface_name].add(dep_name)
            except Exception as e:
                self._logger.warning(f"Could not analyze {interface_name}: {e}")

        self._logger.info(f"Built dependency graph with {len(self._graph)} nodes")

    def detect_circular_dependencies(self) -> list[list[str]]:
        """Detect circular dependencies in the graph."""
        cycles = []
        self._visited.clear()
        self._recursion_stack.clear()

        def dfs(node: str, path: list[str]) -> None:
            if node in self._recursion_stack:
                cycle_start = path.index(node)
                cycle = path[cycle_start:] + [node]
                cycles.append(cycle)
                return
            if node in self._visited:
                return
            self._visited.add(node)
            self._recursion_stack.add(node)
            path.append(node)
            for neighbor in self._graph.get(node, set()):
                dfs(neighbor, path.copy())
            self._recursion_stack.remove(node)

        for node in self._graph:
            if node not in self._visited:
                dfs(node, [])

        if cycles:
            self._logger.warning(f"Found {len(cycles)} circular dependencies")
        else:
            self._logger.info("No circular dependencies detected")
        return cycles

    def validate_all_dependencies(self) -> list[tuple[str, str]]:
        """Validate that all dependencies can be resolved."""
        missing = []
        for node, deps in self._graph.items():
            for dep in deps:
                if dep not in self._graph:
                    found = False
                    for reg_node in self._graph:
                        if reg_node.endswith(dep.split(".")[-1]):
                            found = True
                            break
                    if not found:
                        missing.append((node, dep))
                        self._logger.warning(f"Missing dependency: {node} depends on {dep}")
        return missing

    def analyze_depth(self) -> dict[str, int]:
        """Analyze dependency depth for each node."""
        depth: dict[str, int] = {}

        def compute_depth(node: str) -> int:
            if node in depth:
                return depth[node]
            if not self._graph.get(node):
                depth[node] = 0
                return 0
            max_depth = 0
            for neighbor in self._graph[node]:
                max_depth = max(max_depth, compute_depth(neighbor) + 1)
            depth[node] = max_depth
            return max_depth

        for node in self._graph:
            compute_depth(node)
        return depth

    def get_health_report(self) -> dict[str, Any]:
        """Generate a health report for the dependency graph."""
        self.build_graph()
        cycles = self.detect_circular_dependencies()
        missing = self.validate_all_dependencies()
        depths = self.analyze_depth()

        total_nodes = len(self._graph)
        nodes_with_deps = sum(1 for deps in self._graph.values() if deps)
        avg_deps = sum(len(deps) for deps in self._graph.values()) / total_nodes if total_nodes > 0 else 0
        max_depth = max(depths.values()) if depths else 0

        return {
            "healthy": len(cycles) == 0 and len(missing) == 0,
            "total_nodes": total_nodes,
            "nodes_with_dependencies": nodes_with_deps,
            "average_dependencies": avg_deps,
            "max_depth": max_depth,
            "circular_dependencies": cycles,
            "missing_dependencies": missing,
            "depth_map": {node: depth for node, depth in depths.items() if depth > 2},
        }

    def print_report(self) -> None:
        """Print a formatted dependency report."""
        report = self.get_health_report()
        print("\n" + "=" * 60)
        print("DEPENDENCY GRAPH VALIDATION REPORT")
        print("=" * 60)
        print(f"Status: {'HEALTHY' if report['healthy'] else 'UNHEALTHY'}")
        print(f"Total Nodes: {report['total_nodes']}")
        print(f"Nodes with Dependencies: {report['nodes_with_dependencies']}")
        print(f"Average Dependencies per Node: {report['average_dependencies']:.2f}")
        print(f"Maximum Dependency Depth: {report['max_depth']}")

        if report["circular_dependencies"]:
            print("\n" + "-" * 40)
            print("CIRCULAR DEPENDENCIES DETECTED:")
            for cycle in report["circular_dependencies"]:
                print(f"  {' -> '.join(cycle)}")

        if report["missing_dependencies"]:
            print("\n" + "-" * 40)
            print("MISSING DEPENDENCIES:")
            for node, dep in report["missing_dependencies"][:20]:
                print(f"  {node} depends on {dep}")

        if report["depth_map"]:
            print("\n" + "-" * 40)
            print("DEEP DEPENDENCIES (depth > 2):")
            for node, depth in list(report["depth_map"].items())[:10]:
                print(f"  {node}: depth={depth}")

        print("=" * 60 + "\n")

    def reset(self) -> None:
        """Reset validator state."""
        self._graph.clear()
        self._visited.clear()
        self._recursion_stack.clear()
        self._logger.info("Dependency graph validator reset")

    def get_node_count(self) -> int:
        """Get number of nodes in graph."""
        return len(self._graph)

    def get_edges(self) -> dict[str, set[str]]:
        """Get all edges in graph."""
        return self._graph.copy()


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_dependency_validator: DependencyGraphValidator | None = None


def get_dependency_validator() -> DependencyGraphValidator:
    """Get singleton instance of DependencyGraphValidator."""
    global _dependency_validator
    if _dependency_validator is None:
        _dependency_validator = DependencyGraphValidator()
    return _dependency_validator


async def validate_dependencies() -> bool:
    """Run dependency validation and return True if healthy."""
    validator = get_dependency_validator()
    report = validator.get_health_report()
    return report["healthy"]


__all__ = [
    "CircularDependencyError",
    "DependencyGraphError",
    "DependencyGraphValidator",
    "get_dependency_validator",
    "validate_dependencies",
]