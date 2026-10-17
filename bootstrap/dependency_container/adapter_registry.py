#!/usr/bin/env python3
"""
Module: adapter_registry.py
Layer: Bootstrap (Dependency Container)

Responsibility: Mendaftarkan semua adapter (implementasi port) ke IoC container
secara dinamis dengan auto-discovery dan penanganan kasus khusus.

FIX v8 (2026-10-16):
    - FIX CRITICAL: path resolution scan menggunakan `Path.parts` (bukan
      string replace "\\\\"), karena di Windows string replace kadang gagal
      menghasilkan module path yang valid -> import gagal -> class
      SQLAlchemyManufacturingRepository tidak ter-scan.
    - FIX: explicit import fallback untuk SQLAlchemyManufacturingRepository
      di dua tempat (discovery + register_all) supaya jaminan terdaftar.
    - FIX: logging lebih detail saat scan gagal.
    - Skip TokenIssuerPort (sudah terdaftar di service_registry).
    - BankPaymentPort → BankAPIPaymentsAdapter.
    - TaxAuthorityCoretaxPort → SQLAlchemyCoreTaxAdapter.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import re
from collections.abc import Callable
from pathlib import Path

from bootstrap.dependency_container.ioc_container import IoCContainer

logger = logging.getLogger(__name__)


# =============================================================================
# Module path helper (cross-platform)
# =============================================================================

def _path_to_module(root: Path, py_file: Path) -> str:
    """
    Konversi path file menjadi module path Python.

    Contoh:
        root = E:\\full_erp_accounting_engine
        py_file = E:\\full_erp_accounting_engine\\adapters\\secondary_impl\\foo.py
        → "adapters.secondary_impl.foo"

    Menggunakan Path.parts (bukan string replace) supaya cross-platform
    dan aman dari bug escaping backslash di Windows.
    """
    rel = py_file.relative_to(root)
    parts = list(rel.parts)
    # Buang ekstensi dari part terakhir
    parts[-1] = Path(parts[-1]).stem
    return ".".join(parts)


class AdapterRegistry:
    """Mendaftarkan semua adapter secara otomatis berdasarkan konvensi penamaan."""

    def __init__(self, container: IoCContainer | None = None):
        self._container = container
        self._is_registered = False
        self._logger = logging.getLogger(f"{__name__}.AdapterRegistry")
        self._registered_ports: set[type] = set()

        # =====================================================================
        # MANUAL MAPPING — untuk semua implementasi yang tidak match otomatis
        # =====================================================================
        self._manual_mapping: dict[str, str] = {
            # --- Core / infra ---
            "CoreTaxPort": "TaxAuthorityCoretaxAdapter",
            "EventPublisherPort": "KafkaEventPublisher",
            "SnapshotStorePort": "PostgresSnapshotStore",
            "AgingReportRepositoryPort": "SQLAlchemyReportRepository",

            # FIX: Gunakan nama class asli (_ConcreteAccountRepository)
            "AccountRepositoryPort": "_ConcreteAccountRepository",

            # --- Persistence repositories ---
            "APRepositoryPort": "SQLAlchemyAPRepository",
            "ARRepositoryPort": "SQLAlchemyARRepository",
            "AuditRepositoryPort": "SQLAlchemyAuditEventAdapter",
            "BankAccountRepositoryPort": "SQLAlchemyBankAccountRepository",
            "CachePort": "SQLAlchemyCacheRepository",
            "EmployeeRepositoryPort": "SQLAlchemyEmployeeRepository",
            "FileStoragePort": "LocalFileStorage",
            "NotificationPort": "ConsoleNotification",
            "FixedAssetRepositoryPort": "SQLAlchemyFixedAssetRepository",
            "IAMUserRepositoryPort": "SQLAlchemyIAMUserRepository",
            "IAMRepositoryPort": "SQLAlchemyIAMRepository",
            "InventoryRepositoryPort": "SQLAlchemyInventoryRepository",
            "JournalRepositoryPort": "SQLAlchemyJournalRepository",
            "LedgerRepositoryPort": "SQLAlchemyLedgerRepository",
            "LegalEntityRepositoryPort": "SQLAlchemyLegalEntityRepository",
            "PayrollRepositoryPort": "SQLAlchemyPayrollRepository",
            "ReadModelProjectionPort": "SQLAlchemyReadModelProjection",
            "TrialBalanceRepositoryPort": "TrialBalanceRepositoryAdapter",
            "BalanceSheetRepositoryPort": "BalanceSheetRepositoryAdapter",
            "IncomeStatementRepositoryPort": "IncomeStatementRepositoryAdapter",

            "CustomerRepositoryPort": "SQLAlchemyCustomerRepository",
            "SupplierRepositoryPort": "SQLAlchemySupplierRepository",
            "UnitOfWorkPort": "SQLAlchemyUnitOfWork",
            "TaxRepositoryPort": "SQLAlchemyTaxRepository",
            "TaxTransactionRepositoryPort": "SQLAlchemyTaxTransactionRepository",
            "GoodsReceiptRepositoryPort": "SQLAlchemyGoodsReceiptRepository",
            "PurchaseOrderRepositoryPort": "SQLAlchemyPurchaseOrderRepository",
            "SalesOrderRepositoryPort": "SQLAlchemySalesOrderRepository",
            "SalesRepositoryPort": "SQLAlchemySalesRepository",
            "BudgetRepositoryPort": "SQLAlchemyBudgetRepository",
            "WorkOrderRepositoryPort": "SQLAlchemyWorkOrderRepository",
            "AMLRepositoryPort": "SQLAlchemyAMLRepository",
            "BillOfMaterialsRepositoryPort": "SQLAlchemyBillOfMaterialsRepository",
            "ProjectRepositoryPort": "SQLAlchemyProjectRepository",
            "UMKMRepositoryPort": "SQLAlchemyUMKMRepository",
            "InventoryValuationRepositoryPort": "SQLAlchemyInventoryValuationRepository",
            "CashBookRepositoryPort": "SQLAlchemyCashBookRepository",
            "ApprovalRepositoryPort": "SQLAlchemyApprovalRepository",
            "FiscalPeriodRepositoryPort": "SQLAlchemyFiscalPeriodRepository",
            "ConsolidationRepositoryPort": "SQLAlchemyConsolidationRepository",
            "ForexRepositoryPort": "SQLAlchemyForexRepository",
            "HedgeRepositoryPort": "SQLAlchemyHedgeRepository",
            "IntangibleAssetRepositoryPort": "SQLAlchemyIntangibleAssetRepository",
            "GoodwillRepositoryPort": "SQLAlchemyGoodwillRepository",
            "OutboxRepositoryPort": "SQLAlchemyOutboxRepository",

            # FIX v8: Manufacturing Repository
            "ManufacturingRepositoryPort": "SQLAlchemyManufacturingRepository",

            "SagaStateStorePort": "SQLAlchemySagaStateStoreRepository",
            "SystemSettingRepositoryPort": "SQLAlchemySystemSettingRepository",
            "TimestampNotaryPort": "TimestampNotaryImpl",
            "BankStatementImportPort": "BankStatementImportAdapter",
            "EncryptionKeyVaultPort": "EncryptionKeyVaultAdapter",
            "HashChainServicePort": "HashChainServiceAdapter",
            "ConsolidationGroupReportPort": "ConsolidationGroupReportAdapter",
            "TaxAuthorityCoretaxPort": "SQLAlchemyCoreTaxAdapter",
            "AnalyticsExportPort": "SQLAlchemyAnalyticsExport",
            "CQRSQueryHandlerPort": "SQLAlchemyCQRSQueryHandler",
            "BankPaymentPort": "BankAPIPaymentsAdapter",
        }

        # =====================================================================
        # EXPLICIT IMPORTS — jaminan kalau dynamic scan gagal
        # Class yang di-import di sini akan selalu tersedia saat matching.
        # =====================================================================
        self._explicit_implementations: list[tuple[str, str]] = [
            # (module_path, class_name)
            (
                "adapters.secondary_impl.sqlalchemy_manufacturing_repository_impl",
                "SQLAlchemyManufacturingRepository",
            ),
        ]

    def set_container(self, container: IoCContainer) -> None:
        self._container = container

    def register_all(self) -> None:
        """Pencarian dan registrasi dinamis semua adapter."""
        if self._is_registered:
            self._logger.debug("Adapter registration already completed.")
            return

        if self._container is None:
            raise RuntimeError("Container not set. Call set_container() first.")

        self._logger.info("Starting dynamic adapter registration...")

        # 1. Temukan semua port
        ports = self._discover_ports()
        self._logger.info(f"Found {len(ports)} port(s)")

        # 2. Temukan semua implementasi + tambahkan explicit
        implementations = self._discover_implementations()
        self._logger.info(f"Found {len(implementations)} implementation(s)")

        # 3. Mapping dan registrasi untuk setiap port
        for port in ports:
            port_name = port.__name__

            if port_name == "TokenIssuerPort":
                self._logger.info(
                    f"Skipping {port_name} (already registered via service registry)"
                )
                continue

            impl = None
            impl_source = ""

            # LANGKAH 1: Manual mapping
            manual_impl_name = self._manual_mapping.get(port_name)
            if manual_impl_name:
                impl = self._find_implementation_by_name(implementations, manual_impl_name)
                if impl:
                    impl_source = f"manual mapping ({manual_impl_name})"
                    self._logger.info(f"Manual mapping: {port_name} → {impl.__name__}")
                else:
                    # FIX v8: fallback import langsung jika tidak ada di daftar
                    impl = self._load_explicit_implementation(manual_impl_name)
                    if impl:
                        impl_source = f"manual mapping (explicit import: {manual_impl_name})"
                        self._logger.info(
                            f"Manual mapping (explicit import): "
                            f"{port_name} → {impl.__name__}"
                        )

            # LANGKAH 2: Auto matching
            if impl is None:
                impl = self._match_port_to_implementation(port, implementations)
                if impl:
                    impl_source = "auto matching"

            # LANGKAH 3: Direct match by port name
            if impl is None:
                impl = self._find_implementation_by_name(implementations, port_name)
                if impl:
                    impl_source = "direct match"
                    self._logger.info(f"Direct match: {port_name} → {impl.__name__}")

            # LANGKAH 4: Stub fallback
            if impl is None:
                self._logger.warning(
                    f"No implementation found for {port_name}, creating concrete Impl"
                )
                factory = self._build_stub_factory(port)
                impl_display_name = f"{port_name}Impl"
                impl_source = "auto-generated Impl"
            else:
                if impl.__name__.endswith(("Port", "Protocol")):
                    raise RuntimeError(
                        f"❌ CRITICAL: Implementation selection returned an "
                        f"interface/port: {impl.__module__}.{impl.__name__} "
                        f"for port {port_name}."
                    )
                factory = self._build_factory(port, impl)
                impl_display_name = impl.__name__

            if self._container.has_registration(port):
                self._container.remove(port)

            self._container.register_singleton(port, factory=factory)
            self._registered_ports.add(port)
            self._logger.info(
                f"✅ Registered {port_name} → {impl_display_name} ({impl_source})"
            )

        self._is_registered = True
        self._logger.info(
            f"Adapter registration completed. {len(self._registered_ports)} ports registered."
        )

    # -------------------------------------------------------------------------
    # Discovery Helpers
    # -------------------------------------------------------------------------

    def _discover_ports(self) -> list[type]:
        """Scan ports/primary dan ports/secondary untuk abstract class."""
        root = Path(__file__).resolve().parent.parent.parent
        ports: list[type] = []
        exclude_names = {"BasePort", "BaseRepository", "BaseProtocol"}
        ignore_keywords = {"InMemory", "Fallback", "Stub", "Mock"}

        for base_dir in [root / "ports" / "primary", root / "ports" / "secondary"]:
            if not base_dir.exists():
                continue
            for py_file in base_dir.glob("*.py"):
                if py_file.name == "__init__.py":
                    continue
                try:
                    module_path = _path_to_module(root, py_file)
                    module = importlib.import_module(module_path)
                except Exception as e:
                    self._logger.warning(f"Could not import {py_file.name}: {e}")
                    continue

                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if name in exclude_names:
                        continue
                    if any(kw in obj.__name__ for kw in ignore_keywords):
                        continue
                    if name.endswith(("Port", "Protocol", "Repository")):
                        if inspect.isabstract(obj):
                            ports.append(obj)
        return ports

    def _discover_implementations(self) -> list[type]:
        """
        Scan folders untuk implementasi konkret.
        FIX v8: gunakan Path.parts (bukan string replace) untuk module path.
        """
        root = Path(__file__).resolve().parent.parent.parent
        search_dirs = [
            root / "adapters",
            root / "adapters" / "secondary_impl",
            root / "ports" / "primary",
            root / "ports" / "secondary",
        ]
        implementations: list[type] = []
        ignore_keywords = {"Stub", "Fallback", "Mock", "Base"}
        seen_names: set[str] = set()

        for base_dir in search_dirs:
            if not base_dir.exists():
                continue
            for py_file in base_dir.glob("*.py"):
                if py_file.name == "__init__.py":
                    continue
                try:
                    module_path = _path_to_module(root, py_file)
                    module = importlib.import_module(module_path)
                except Exception as e:
                    self._logger.warning(f"Could not scan {py_file}: {e}")
                    continue

                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if name.endswith(("Port", "Protocol", "Base")):
                        continue
                    if any(kw in name for kw in ignore_keywords):
                        continue
                    if inspect.isabstract(obj):
                        continue
                    # Hindari duplikat (bisa muncul karena import di __init__)
                    if name in seen_names and obj.__module__ != module_path:
                        continue
                    implementations.append(obj)
                    seen_names.add(name)

        # =====================================================================
        # FIX v8: EXPLICIT import — jaminan kalau dynamic scan gagal silent
        # =====================================================================
        for mod_path, cls_name in self._explicit_implementations:
            try:
                mod = importlib.import_module(mod_path)
                cls = getattr(mod, cls_name, None)
                if cls is None:
                    self._logger.error(
                        f"EXPLICIT: class {cls_name} not found in {mod_path}"
                    )
                    continue
                if not any(i.__name__ == cls_name for i in implementations):
                    implementations.append(cls)
                    self._logger.info(f"EXPLICIT: Added {cls_name} from {mod_path}")
            except Exception as e:
                self._logger.error(
                    f"EXPLICIT: Failed to import {cls_name} from {mod_path}: {e}"
                )

        return implementations

    def _load_explicit_implementation(self, class_name: str) -> type | None:
        """
        Cari class dengan nama `class_name` di seluruh module yang
        terdaftar di `_explicit_implementations`.
        Digunakan sebagai fallback saat matching gagal.
        """
        for mod_path, cls_name in self._explicit_implementations:
            if cls_name != class_name:
                continue
            try:
                mod = importlib.import_module(mod_path)
                cls = getattr(mod, cls_name, None)
                if cls is not None:
                    return cls
            except Exception as e:
                self._logger.error(
                    f"Fallback import failed for {cls_name}: {e}"
                )
        return None

    def _find_implementation_by_name(
        self, implementations: list[type], name: str
    ) -> type | None:
        for impl in implementations:
            if impl.__name__ == name:
                return impl
        return None

    # -------------------------------------------------------------------------
    # Matching & Factory
    # -------------------------------------------------------------------------

    def _match_port_to_implementation(
        self, port: type, implementations: list[type]
    ) -> type | None:
        port_name = port.__name__
        base_name = port_name
        if port_name.endswith("Protocol"):
            base_name = port_name[:-8]
        return self._match_by_base_name(base_name, implementations)

    def _match_by_base_name(
        self, base_name: str, implementations: list[type]
    ) -> type | None:
        clean = re.sub(r"(Port|Protocol|RepositoryPort|Repository)$", "", base_name)
        if not clean:
            return None

        candidates = []
        for impl in implementations:
            impl_name = impl.__name__
            if impl_name.endswith(("Port", "Protocol")):
                continue

            if impl_name.startswith("SQLAlchemy") and clean in impl_name:
                candidates.append((impl, 10))
            elif impl_name.startswith(clean) and (
                impl_name.endswith("Repository") or impl_name == clean
            ):
                candidates.append((impl, 8))
            elif impl_name == f"{clean}Adapter":
                candidates.append((impl, 7))
            elif impl_name == f"{clean}Impl":
                candidates.append((impl, 6))
            elif impl_name == clean and impl_name != base_name:
                candidates.append((impl, 5))

        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            return candidates[0][0]
        return None

    def _build_factory(self, port: type, impl: type) -> Callable:
        port_name = port.__name__
        impl_name = impl.__name__

        if impl_name.endswith(("Port", "Protocol")):
            raise RuntimeError(
                f"❌ CRITICAL: _build_factory received an interface/port as "
                f"implementation: {impl.__module__}.{impl_name} for port {port_name}."
            )

        # === KASUS KHUSUS ===
        if port_name == "CoreTaxPort" and impl_name == "TaxAuthorityCoretaxAdapter":
            sig = inspect.signature(impl.__init__)
            params = sig.parameters
            if "session" in params:
                session_param = params["session"]
                if session_param.default is not inspect.Parameter.empty:
                    def coretax_factory():
                        return impl()
                else:
                    def coretax_factory():
                        return impl(session=None)
            else:
                def coretax_factory():
                    return impl()
            coretax_factory.__name__ = "factory_TaxAuthorityCoretaxAdapter"
            return coretax_factory

        if port_name == "SnapshotStorePort" and impl_name == "PostgresSnapshotStore":
            def snapshot_factory():
                return impl()
            snapshot_factory.__name__ = "factory_PostgresSnapshotStore"
            return snapshot_factory

        if port_name == "HashChainServicePort" and impl_name == "HashChainServiceAdapter":
            def hashchain_factory():
                return impl(chain_type="default", chain_id="default")
            hashchain_factory.__name__ = "factory_HashChainServiceAdapter"
            return hashchain_factory

        # === KASUS UMUM ===
        sig = inspect.signature(impl.__init__)
        params = sig.parameters
        required_params = [
            p for p in params.values()
            if p.default is inspect.Parameter.empty and p.name != "self"
        ]

        if "session" in params:
            session_param = params["session"]
            if session_param.default is not inspect.Parameter.empty:
                def factory():
                    return impl()
            else:
                def factory():
                    return impl(session=None)
        else:
            if required_params:
                def factory():
                    kwargs = {p.name: None for p in required_params}
                    return impl(**kwargs)
            else:
                def factory():
                    return impl()

        factory.__name__ = f"factory_{impl_name}"
        return factory

    def _build_stub_factory(self, port: type) -> Callable:
        port_name = port.__name__
        port_module = port.__module__
        mod = importlib.import_module(port_module)
        port_cls = getattr(mod, port_name)

        class_name = f"{port_name}Impl"

        abstract_methods = set()
        for base in port_cls.__bases__:
            if hasattr(base, "__abstractmethods__"):
                abstract_methods.update(base.__abstractmethods__)
        if hasattr(port_cls, "__abstractmethods__"):
            abstract_methods.update(port_cls.__abstractmethods__)

        methods = {}
        for method_name in abstract_methods:
            def make_stub(name):
                def stub(self, *args, **kwargs):
                    raise NotImplementedError(
                        f"Method '{name}' not implemented in {class_name}"
                    )
                return stub
            methods[method_name] = make_stub(method_name)

        impl_class = type(class_name, (port_cls,), methods)

        def stub_factory():
            return impl_class()

        stub_factory.__name__ = f"factory_{class_name}"
        return stub_factory

    # -------------------------------------------------------------------------
    # Public utility
    # -------------------------------------------------------------------------

    def get_registered_ports(self) -> list[type]:
        return list(self._registered_ports)

    def reset(self) -> None:
        self._registered_ports.clear()
        self._is_registered = False


# -----------------------------------------------------------------------------
# Singleton instance
# -----------------------------------------------------------------------------

_adapter_registry: AdapterRegistry | None = None


def get_adapter_registry() -> AdapterRegistry:
    global _adapter_registry
    if _adapter_registry is None:
        from bootstrap.dependency_container.ioc_container import get_container
        container = get_container()
        _adapter_registry = AdapterRegistry(container)
        _adapter_registry.register_all()
    return _adapter_registry


def set_adapter_registry_instance(registry: AdapterRegistry) -> None:
    global _adapter_registry
    _adapter_registry = registry


__all__ = [
    "AdapterRegistry",
    "get_adapter_registry",
    "set_adapter_registry_instance",
]
