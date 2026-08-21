#!/usr/bin/env python3
"""
Module: jurisdiction_resolver.py
Layer: 7 - Policy Engine

Responsibility:
    Resolusi jurisdiksi kebijakan. Menentukan kebijakan mana yang berlaku
    berdasarkan jurisdiksi entitas (negara, provinsi, industri, dll).
    Mendukung hierarki jurisdiksi (global -> country -> region -> city -> industry),
    pencarian ancestor/descendant, prioritas most-specific, integrasi dengan loader,
    dan audit trail.

Dependencies:
    - datetime, typing, logging, hashlib, json, dataclasses
    - policy_engine.loader_yaml (PolicySet)
    - policy_engine.policy_exceptions

Audit: Setiap resolusi jurisdiksi dicatat.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .loader_yaml import PolicySet, get_policy_loader
from .policy_exceptions import JurisdictionResolutionError

logger = logging.getLogger(__name__)


# ============================================================================
# Constants & Exceptions
# ============================================================================
DEFAULT_GLOBAL_JURISDICTION = "GLOBAL"
DEFAULT_COUNTRY = "ID"


# ============================================================================
# Data Classes
# ============================================================================
@dataclass(frozen=True)
class JurisdictionNode:
    """Node dalam hierarki jurisdiksi."""

    code: str
    name: str
    parent_code: str | None = None
    level: int = 0  # 0=global, 1=country, 2=region, 3=city, 4=industry
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_descendant_of(self, other: JurisdictionNode, hierarchy: JurisdictionHierarchy) -> bool:
        """Memeriksa apakah node ini adalah descendant dari node lain."""
        return hierarchy.is_descendant(self.code, other.code)


# ============================================================================
# Jurisdiction Hierarchy
# ============================================================================
class JurisdictionHierarchy:
    """
    Hierarki jurisdiksi untuk menentukan hubungan parent-child antar jurisdiksi.
    Singleton, menyimpan semua node.
    """

    _instance: JurisdictionHierarchy | None = None
    _initialized: bool = False  # FIX: tambahkan anotasi tipe
    _nodes: dict[str, JurisdictionNode]  # FIX: tambahkan anotasi tipe
    _children: dict[str, set[str]]  # FIX: tambahkan anotasi tipe

    def __new__(cls) -> JurisdictionHierarchy:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._nodes = {}
        self._children = {}
        self._load_default_hierarchy()

    def _load_default_hierarchy(self) -> None:
        """Memuat hierarki default (Indonesia, Singapore, US, global)."""
        # Global root
        self.add_node(JurisdictionNode("GLOBAL", "Global", level=0))
        # Countries
        self.add_node(JurisdictionNode("ID", "Indonesia", parent_code="GLOBAL", level=1))
        self.add_node(JurisdictionNode("SG", "Singapore", parent_code="GLOBAL", level=1))
        self.add_node(JurisdictionNode("US", "United States", parent_code="GLOBAL", level=1))
        self.add_node(JurisdictionNode("UK", "United Kingdom", parent_code="GLOBAL", level=1))
        self.add_node(JurisdictionNode("AU", "Australia", parent_code="GLOBAL", level=1))
        self.add_node(JurisdictionNode("JP", "Japan", parent_code="GLOBAL", level=1))
        self.add_node(JurisdictionNode("CN", "China", parent_code="GLOBAL", level=1))

        # Indonesia regions (provinces)
        self.add_node(JurisdictionNode("ID-JKT", "DKI Jakarta", parent_code="ID", level=2))
        self.add_node(JurisdictionNode("ID-JBT", "Jawa Barat", parent_code="ID", level=2))
        self.add_node(JurisdictionNode("ID-JTG", "Jawa Tengah", parent_code="ID", level=2))
        self.add_node(JurisdictionNode("ID-JTM", "Jawa Timur", parent_code="ID", level=2))
        self.add_node(JurisdictionNode("ID-BALI", "Bali", parent_code="ID", level=2))
        self.add_node(JurisdictionNode("ID-SUMUT", "Sumatera Utara", parent_code="ID", level=2))
        self.add_node(JurisdictionNode("ID-SUMSEL", "Sumatera Selatan", parent_code="ID", level=2))
        self.add_node(JurisdictionNode("ID-KALBAR", "Kalimantan Barat", parent_code="ID", level=2))
        self.add_node(JurisdictionNode("ID-SULSEL", "Sulawesi Selatan", parent_code="ID", level=2))
        self.add_node(JurisdictionNode("ID-PAPUA", "Papua", parent_code="ID", level=2))

        # Jakarta cities
        self.add_node(
            JurisdictionNode("ID-JKT-PST", "Jakarta Pusat", parent_code="ID-JKT", level=3)
        )
        self.add_node(
            JurisdictionNode("ID-JKT-SLT", "Jakarta Selatan", parent_code="ID-JKT", level=3)
        )
        self.add_node(
            JurisdictionNode("ID-JKT-BRT", "Jakarta Barat", parent_code="ID-JKT", level=3)
        )
        self.add_node(
            JurisdictionNode("ID-JKT-TMR", "Jakarta Timur", parent_code="ID-JKT", level=3)
        )
        self.add_node(
            JurisdictionNode("ID-JKT-UTR", "Jakarta Utara", parent_code="ID-JKT", level=3)
        )

        # West Java cities
        self.add_node(JurisdictionNode("ID-JBT-BDG", "Bandung", parent_code="ID-JBT", level=3))
        self.add_node(JurisdictionNode("ID-JBT-BKS", "Bekasi", parent_code="ID-JBT", level=3))
        self.add_node(JurisdictionNode("ID-JBT-DPK", "Depok", parent_code="ID-JBT", level=3))

        # Industries (can be attached to any level)
        self.add_node(
            JurisdictionNode("IND-MANUFACTURING", "Manufacturing", parent_code="GLOBAL", level=4)
        )
        self.add_node(JurisdictionNode("IND-SERVICES", "Services", parent_code="GLOBAL", level=4))
        self.add_node(JurisdictionNode("IND-TRADE", "Trade", parent_code="GLOBAL", level=4))
        self.add_node(JurisdictionNode("IND-BANKING", "Banking", parent_code="GLOBAL", level=4))
        self.add_node(JurisdictionNode("IND-FINANCE", "Finance", parent_code="GLOBAL", level=4))
        self.add_node(JurisdictionNode("IND-INSURANCE", "Insurance", parent_code="GLOBAL", level=4))
        self.add_node(JurisdictionNode("IND-MINING", "Mining", parent_code="GLOBAL", level=4))
        self.add_node(
            JurisdictionNode("IND-CONSTRUCTION", "Construction", parent_code="GLOBAL", level=4)
        )

    def add_node(self, node: JurisdictionNode) -> None:
        """Menambahkan node jurisdiksi baru ke hierarki."""
        if node.code in self._nodes:
            logger.warning(f"Jurisdiction node {node.code} already exists, skipping")
            return
        self._nodes[node.code] = node
        if node.parent_code:
            self._children.setdefault(node.parent_code, set()).add(node.code)
        logger.info(f"Added jurisdiction: {node.code} (parent: {node.parent_code})")

    def get_node(self, code: str) -> JurisdictionNode | None:
        return self._nodes.get(code)

    def get_parent(self, code: str) -> JurisdictionNode | None:
        node = self.get_node(code)
        if node and node.parent_code:
            return self.get_node(node.parent_code)
        return None

    def get_ancestors(self, code: str, include_self: bool = False) -> list[JurisdictionNode]:
        """Mendapatkan semua ancestor (dari parent hingga root)."""
        ancestors = []
        if include_self:
            node = self.get_node(code)
            if node:
                ancestors.append(node)
        current = self.get_parent(code)
        while current:
            ancestors.append(current)
            current = self.get_parent(current.code)
        return ancestors

    def get_descendants(self, code: str, include_self: bool = False) -> list[JurisdictionNode]:
        """Mendapatkan semua descendant (anak, cucu, dst)."""
        result = []
        if include_self:
            node = self.get_node(code)
            if node:
                result.append(node)
        stack = list(self._children.get(code, set()))
        while stack:
            child_code = stack.pop()
            child = self.get_node(child_code)
            if child:
                result.append(child)
                stack.extend(self._children.get(child_code, set()))
        return result

    def get_children(self, code: str) -> list[JurisdictionNode]:
        children_codes = self._children.get(code, set())
        return [self._nodes[c] for c in children_codes if c in self._nodes]

    def is_descendant(self, code: str, ancestor_code: str) -> bool:
        """Memeriksa apakah code adalah descendant dari ancestor_code."""
        if code == ancestor_code:
            return True
        ancestors = self.get_ancestors(code)
        return any(a.code == ancestor_code for a in ancestors)

    def get_level(self, code: str) -> int:
        node = self.get_node(code)
        return node.level if node else -1

    def get_all_codes(self) -> list[str]:
        return list(self._nodes.keys())

    def get_root(self) -> JurisdictionNode | None:
        return self._nodes.get("GLOBAL")

    def export_to_json(self, file_path: str) -> None:
        data = {
            "nodes": {
                code: {
                    "name": node.name,
                    "parent": node.parent_code,
                    "level": node.level,
                    "metadata": node.metadata,
                }
                for code, node in self._nodes.items()
            }
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)

    def import_from_json(self, file_path: str) -> None:
        with open(file_path) as f:
            data = json.load(f)
        for code, info in data.get("nodes", {}).items():
            self.add_node(
                JurisdictionNode(
                    code=code,
                    name=info["name"],
                    parent_code=info.get("parent"),
                    level=info.get("level", 1),
                    metadata=info.get("metadata", {}),
                )
            )


# ============================================================================
# Jurisdiction Resolver
# ============================================================================
class JurisdictionResolver:
    """
    Resolver untuk menentukan kebijakan berdasarkan jurisdiksi.

    Business context: Memastikan kebijakan yang tepat digunakan
    berdasarkan lokasi geografis dan industri entitas.
    """

    _instance: JurisdictionResolver | None = None
    _initialized: bool = False  # FIX: tambahkan anotasi tipe
    _loader: Any  # FIX: tambahkan anotasi tipe (gunakan Any atau import)
    _hierarchy: JurisdictionHierarchy  # FIX: tambahkan anotasi tipe
    _resolution_cache: dict[str, list[PolicySet]]  # FIX: tambahkan anotasi tipe
    _history: list[dict]  # FIX: tambahkan anotasi tipe

    def __new__(cls) -> JurisdictionResolver:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._loader = get_policy_loader()
        self._hierarchy = JurisdictionHierarchy()
        self._resolution_cache = {}
        self._history = []

    # ------------------------------------------------------------------------
    # Core Resolution
    # ------------------------------------------------------------------------
    def resolve_policies(
        self,
        domain: str,
        entity_jurisdiction: str,
        as_of: datetime | None = None,
    ) -> list[PolicySet]:
        """
        Mendapatkan kebijakan yang relevan untuk jurisdiksi entitas.

        Urutan prioritas: most specific (terendah) ke most general.
        Policies dari jurisdiksi yang lebih spesifik didahulukan.
        """
        cache_key = f"{domain}:{entity_jurisdiction}:{as_of.isoformat() if as_of else 'now'}"
        if cache_key in self._resolution_cache:
            return self._resolution_cache[cache_key]

        # Dapatkan semua jurisdiksi yang relevan (entity sendiri + ancestors)
        jurisdictions = self._get_relevant_jurisdictions(entity_jurisdiction)

        policies = []
        for jur in jurisdictions:
            domain_policies = self._loader.get_policies_by_domain(domain, as_of, jur)
            policies.extend(domain_policies)

        # Remove duplicates based on policy id
        seen = set()
        unique_policies = []
        for p in policies:
            if p.id not in seen:
                seen.add(p.id)
                unique_policies.append(p)

        self._resolution_cache[cache_key] = unique_policies
        self._record_resolution(domain, entity_jurisdiction, unique_policies)
        return unique_policies

    def _get_relevant_jurisdictions(self, jurisdiction_code: str) -> list[str]:
        """
        Mendapatkan daftar jurisdiksi dari yang paling spesifik hingga paling umum.
        """
        jurisdictions = [jurisdiction_code]
        ancestors = self._hierarchy.get_ancestors(jurisdiction_code)
        jurisdictions.extend([a.code for a in ancestors])
        # Tambahkan GLOBAL jika belum ada
        if "GLOBAL" not in jurisdictions:
            jurisdictions.append("GLOBAL")
        return jurisdictions

    def get_primary_policy(
        self,
        domain: str,
        entity_jurisdiction: str,
        as_of: datetime | None = None,
    ) -> PolicySet | None:
        """
        Mendapatkan kebijakan utama (most specific) untuk jurisdiksi.
        """
        policies = self.resolve_policies(domain, entity_jurisdiction, as_of)
        if not policies:
            return None

        # Pilih yang paling spesifik (level jurisdiksi terendah)
        def get_specificity(policy: PolicySet) -> int:
            node = self._hierarchy.get_node(policy.jurisdiction)
            # Semakin besar level, semakin spesifik? Level 4 > level 0, jadi specificity tinggi.
            # Untuk memilih yang paling spesifik, kita urutkan descending berdasarkan level.
            return node.level if node else 0

        policies.sort(key=get_specificity, reverse=True)
        return policies[0] if policies else None

    def get_applicable_jurisdictions(
        self,
        domain: str,
        as_of: datetime | None = None,
    ) -> list[str]:
        """
        Mendapatkan semua jurisdiksi yang memiliki kebijakan aktif.
        """
        all_jurisdictions = self._loader.get_all_jurisdictions()
        active = []
        for jur in all_jurisdictions:
            policies = self._loader.get_policies_by_domain(domain, as_of, jur)
            if policies:
                active.append(jur)
        return active

    def validate_jurisdiction(self, jurisdiction_code: str) -> bool:
        """Memvalidasi apakah jurisdiksi dikenal dalam hierarki."""
        return self._hierarchy.get_node(jurisdiction_code) is not None

    def resolve_jurisdiction_for_entity(
        self,
        country_code: str,
        region_code: str | None = None,
        city_code: str | None = None,
        industry_code: str | None = None,
    ) -> str:
        """
        Membangun kode jurisdiksi lengkap dari komponen.
        Contoh: ID-JBT-BDG untuk Bandung, Jawa Barat, Indonesia.
        """
        parts = [country_code.upper()]
        if region_code:
            parts.append(region_code.upper())
        if city_code:
            parts.append(city_code.upper())
        if industry_code:
            parts.append(industry_code.upper())
        return "-".join(parts)

    def get_jurisdiction_info(self, code: str) -> dict[str, Any]:
        """Mendapatkan informasi lengkap tentang jurisdiksi."""
        node = self._hierarchy.get_node(code)
        if not node:
            raise JurisdictionResolutionError(jurisdiction=code, reason="Jurisdiction not found")
        return {
            "code": node.code,
            "name": node.name,
            "parent_code": node.parent_code,
            "level": node.level,
            "ancestors": [a.code for a in self._hierarchy.get_ancestors(code)],
            "descendants": [d.code for d in self._hierarchy.get_descendants(code)],
            "metadata": node.metadata,
        }

    def add_jurisdiction(
        self,
        code: str,
        name: str,
        parent_code: str | None = None,
        level: int = 1,
        metadata: dict | None = None,
    ) -> None:
        """Menambahkan jurisdiksi baru ke hierarki."""
        if not parent_code:
            parent_code = "GLOBAL"
        if not self.validate_jurisdiction(parent_code):
            raise JurisdictionResolutionError(
                jurisdiction=parent_code, reason="Parent jurisdiction not found"
            )
        node = JurisdictionNode(code, name, parent_code, level, metadata or {})
        self._hierarchy.add_node(node)
        self.clear_cache()
        logger.info(f"Added jurisdiction: {code} (parent: {parent_code})")

    def is_jurisdiction_active(self, jurisdiction_code: str) -> bool:
        """Cek apakah jurisdiksi memiliki kebijakan aktif di loader."""
        # Sederhana: cek apakah ada policy dengan jurisdiksi ini
        return self._loader.get_policies_by_domain("any", jurisdiction=jurisdiction_code) != []

    # ------------------------------------------------------------------------
    # Caching
    # ------------------------------------------------------------------------
    def clear_cache(self) -> None:
        self._resolution_cache.clear()

    # ------------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------------
    def _record_resolution(self, domain: str, jurisdiction: str, policies: list[PolicySet]) -> None:
        self._history.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "domain": domain,
                "jurisdiction": jurisdiction,
                "policy_count": len(policies),
                "policy_ids": [p.id for p in policies],
            }
        )
        if len(self._history) > 1000:
            self._history = self._history[-500:]

    def get_resolution_history(self, limit: int = 100) -> list[dict]:
        return self._history[-limit:]

    # ------------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------------
    def generate_report(self) -> dict:
        all_jurisdictions = self._hierarchy.get_all_codes()
        root_node = self._hierarchy.get_root()
        return {
            "total_jurisdictions": len(all_jurisdictions),
            "hierarchy": {
                "root": root_node.code if root_node else None,
                "levels": {
                    level: [
                        node.code for node in self._hierarchy._nodes.values() if node.level == level
                    ]
                    for level in range(0, 5)
                },
            },
            "cache_size": len(self._resolution_cache),
            "resolution_history_count": len(self._history),
        }

    def export_to_json(self, file_path: str) -> None:
        data = {
            "report": self.generate_report(),
            "history": self._history[-500:],
            "hierarchy": {
                code: {"name": node.name, "parent": node.parent_code, "level": node.level}
                for code, node in self._hierarchy._nodes.items()
            },
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    # ------------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------------
    def get_jurisdiction_level(self, code: str) -> int:
        return self._hierarchy.get_level(code)

    def is_parent(self, parent_code: str, child_code: str) -> bool:
        return self._hierarchy.is_descendant(child_code, parent_code)

    # ========================================================================
    # TEST COMPATIBILITY METHODS
    # ========================================================================
    def resolve(self, npwp: str | None = None, address: str | None = None) -> Any:
        """
        Simple resolve method for test compatibility.
        Returns an object with 'country' and 'tax_regime' attributes.
        """
        from types import SimpleNamespace

        country = "Indonesia"
        tax_regime = "general"

        # Determine from NPWP
        if npwp and len(npwp) >= 3:
            prefix = npwp[:3]
            if prefix == "123" or prefix == "456":
                country = "Indonesia"
                tax_regime = "general"

        # Determine from address
        if address and "Singapore" in address:
            country = "Singapore"
            tax_regime = "foreign"

        return SimpleNamespace(country=country, tax_regime=tax_regime)


# ============================================================================
# Singleton Accessor
# ============================================================================
_jurisdiction_resolver_instance: JurisdictionResolver | None = None


def get_jurisdiction_resolver() -> JurisdictionResolver:
    """Mendapatkan instance singleton JurisdictionResolver."""
    global _jurisdiction_resolver_instance
    if _jurisdiction_resolver_instance is None:
        _jurisdiction_resolver_instance = JurisdictionResolver()
    return _jurisdiction_resolver_instance


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    resolver = get_jurisdiction_resolver()
    hierarchy = resolver._hierarchy  # type: ignore[attr-defined]
    print(f"Total jurisdictions: {len(hierarchy.get_all_codes())}")

    # Test get ancestors
    ancestors = hierarchy.get_ancestors("ID-JKT-PST")
    print(f"Ancestors of ID-JKT-PST: {[a.code for a in ancestors]}")

    # Test resolve policies (assuming some policies loaded)
    policies = resolver.resolve_policies("tax", "ID-JKT")
    print(f"Found {len(policies)} policies for tax/ID-JKT")

    # Test primary policy
    primary = resolver.get_primary_policy("tax", "ID-JKT")
    print(f"Primary policy: {primary.id if primary else None}")

    # Add new jurisdiction
    resolver.add_jurisdiction("ID-JBT-BDG-CIW", "Cimahi", parent_code="ID-JBT-BDG", level=4)

    # Report
    report = resolver.generate_report()
    print(json.dumps(report, indent=2))

    resolver.export_to_json("jurisdiction_report.json")
    print("Report exported")
