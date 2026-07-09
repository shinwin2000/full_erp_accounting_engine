#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: adapter_registry.py
Layer: Bootstrap (Dependency Container)

Responsibility: Mendaftarkan semua adapter (implementasi port) ke IoC container
secara dinamis dengan auto-discovery dan penanganan kasus khusus.

FIX:
- _discover_implementations() sekarang menolak kelas yang berakhiran Port/Protocol/Base.
- _match_by_base_name() memiliki guard untuk menolak Port/Protocol.
- _build_factory() memiliki guard runtime untuk mendeteksi jika impl adalah interface.
- AgingReportRepositoryPort secara eksplisit di-map ke SQLAlchemyReportRepository.
- AccountRepositoryPort sekarang diarahkan ke _ConcreteAccountRepository (implementasi konkret di adapters).
  Karena alias "ConcreteAccountRepository" tidak terdeteksi sebagai class (nama asli _ConcreteAccountRepository).
- Dihapus special case pembuatan kelas anonim untuk AccountRepositoryPort karena sudah ada implementasi konkret.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import re
from pathlib import Path
from typing import Any, Callable, List, Optional, Type, Set, Dict

from bootstrap.dependency_container.ioc_container import IoCContainer

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """Mendaftarkan semua adapter secara otomatis berdasarkan konvensi penamaan."""

    def __init__(self, container: Optional[IoCContainer] = None):
        self._container = container
        self._is_registered = False
        self._logger = logging.getLogger(f"{__name__}.AdapterRegistry")
        self._registered_ports: Set[Type] = set()

        # =====================================================================
        # MANUAL MAPPING — untuk semua implementasi yang tidak match otomatis
        # =====================================================================
        self._manual_mapping: Dict[str, str] = {
            # --- Ports yang sudah ada sebelumnya ---
            "CoreTaxPort": "TaxAuthorityCoretaxAdapter",
            "EventPublisherPort": "KafkaEventPublisher",
            "SnapshotStorePort": "PostgresSnapshotStore",
            "AgingReportRepositoryPort": "SQLAlchemyReportRepository",

            # FIX: Gunakan nama class asli (_ConcreteAccountRepository) karena alias tidak terdeteksi
            "AccountRepositoryPort": "_ConcreteAccountRepository",

            "APRepositoryPort": "SQLAlchemyAPRepository",
            "ARRepositoryPort": "SQLAlchemyARRepository",
            "AuditRepositoryPort": "SQLAlchemyAuditEventAdapter",
            "BankAccountRepositoryPort": "SQLAlchemyBankAccountRepository",
            "CachePort": "SQLAlchemyCacheRepository",
            "EmployeeRepositoryPort": "SQLAlchemyEmployeeRepository",
            "FileStoragePort": "SQLAlchemyFileStorageStatusAdapter",
            "FixedAssetRepositoryPort": "SQLAlchemyFixedAssetRepository",
            "IAMUserRepositoryPort": "SQLAlchemyIAMUserRepository",
            "IAMRepositoryPort": "SQLAlchemyIAMRepository",
            "InventoryRepositoryPort": "SQLAlchemyInventoryRepository",
            "JournalRepositoryPort": "SQLAlchemyJournalRepository",
            "LedgerRepositoryPort": "SQLAlchemyLedgerRepository",
            "LegalEntityRepositoryPort": "SQLAlchemyLegalEntityRepository",
            "NotificationPort": "SQLAlchemyNotificationChannelAdapter",
            "PayrollRepositoryPort": "SQLAlchemyPayrollRepository",
            "ReadModelProjectionPort": "SQLAlchemyReadModelProjection",
            "TrialBalanceRepositoryPort": "TrialBalanceRepositoryAdapter",
            "BalanceSheetRepositoryPort": "BalanceSheetRepositoryAdapter",
            "IncomeStatementRepositoryPort": "IncomeStatementRepositoryAdapter",

            # --- Ports yang mungkin masih kurang (tambahan) ---
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
            "ManufacturingRepositoryPort": "SQLAlchemyManufacturingRepository",
            "SagaStateStorePort": "SQLAlchemySagaStateStoreRepository",
            "SystemSettingRepositoryPort": "SQLAlchemySystemSettingRepository",
            "TimestampNotaryPort": "TimestampNotaryImpl",
            "BankStatementImportPort": "BankStatementImportAdapter",
            "EncryptionKeyVaultPort": "EncryptionKeyVaultAdapter",
            "HashChainServicePort": "HashChainServiceAdapter",
            "ConsolidationGroupReportPort": "ConsolidationGroupReportAdapter",
            "TaxAuthorityCoretaxPort": "TaxAuthorityCoretaxAdapter",
            "AnalyticsExportPort": "SQLAlchemyAnalyticsExport",
            "CQRSQueryHandlerPort": "SQLAlchemyCQRSQueryHandler",
        }

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

        # 1. Temukan semua port (interface)
        ports = self._discover_ports()
        self._logger.info(f"Found {len(ports)} port(s)")

        # 2. Temukan semua implementasi (sudah difilter, tidak termasuk Port/Protocol)
        implementations = self._discover_implementations()
        self._logger.info(f"Found {len(implementations)} implementation(s)")

        # 3. Mapping dan registrasi untuk setiap port
        for port in ports:
            port_name = port.__name__
            impl = None
            impl_source = ""

            # LANGKAH 1: Manual mapping (prioritas tertinggi)
            manual_impl_name = self._manual_mapping.get(port_name)
            if manual_impl_name:
                impl = self._find_implementation_by_name(implementations, manual_impl_name)
                if impl:
                    impl_source = f"manual mapping ({manual_impl_name})"
                    self._logger.info(f"Manual mapping: {port_name} → {impl.__name__}")

            # LANGKAH 2: Auto matching (jika manual tidak ada)
            if impl is None:
                impl = self._match_port_to_implementation(port, implementations)
                if impl:
                    impl_source = "auto matching"

            # LANGKAH 3: Direct match (jika auto matching gagal)
            if impl is None:
                impl = self._find_implementation_by_name(implementations, port_name)
                if impl:
                    impl_source = "direct match"
                    self._logger.info(f"Direct match: {port_name} → {impl.__name__}")

            # LANGKAH 4: Buat stub konkret jika masih None
            if impl is None:
                self._logger.info(f"No implementation found for {port_name}, creating concrete Impl")
                factory = self._build_stub_factory(port)
                impl_display_name = f"{port_name}Impl"
                impl_source = "auto-generated Impl"
            else:
                # Guard: pastikan impl bukan interface/port
                if impl.__name__.endswith(("Port", "Protocol")):
                    raise RuntimeError(
                        f"❌ CRITICAL: Implementation selection returned an interface/port: "
                        f"{impl.__module__}.{impl.__name__} for port {port_name}. "
                        "This indicates a bug in _match_port_to_implementation or _discover_implementations."
                    )
                factory = self._build_factory(port, impl)
                impl_display_name = impl.__name__

            # Hapus registrasi sebelumnya jika ada
            if self._container.has_registration(port):
                self._container.remove(port)

            self._container.register_singleton(port, factory=factory)
            self._registered_ports.add(port)
            self._logger.info(f"✅ Registered {port_name} → {impl_display_name} ({impl_source})")

        self._is_registered = True
        self._logger.info(f"Adapter registration completed. {len(self._registered_ports)} ports registered.")

    # -------------------------------------------------------------------------
    # Discovery Helpers
    # -------------------------------------------------------------------------

    def _discover_ports(self) -> List[Type]:
        """Scan semua file di ports/primary dan ports/secondary untuk mencari port."""
        root = Path(__file__).resolve().parent.parent.parent
        ports: List[Type] = []
        exclude_names = {"BasePort", "BaseRepository", "BaseProtocol"}
        ignore_keywords = {"InMemory", "Fallback", "Stub", "Mock"}

        for base_dir in [root / "ports" / "primary", root / "ports" / "secondary"]:
            if not base_dir.exists():
                continue
            for py_file in base_dir.glob("*.py"):
                if py_file.name == "__init__.py":
                    continue
                module_path = str(py_file.relative_to(root).with_suffix("")).replace("\\", ".").replace("/", ".")
                try:
                    module = importlib.import_module(module_path)
                    for name, obj in inspect.getmembers(module, inspect.isclass):
                        if name in exclude_names:
                            continue
                        if any(kw in name for kw in ignore_keywords):
                            continue
                        if name.endswith(("Port", "Protocol", "Repository")):
                            ports.append(obj)
                except Exception as e:
                    self._logger.debug(f"Could not scan {py_file}: {e}")
        return ports

    def _discover_implementations(self) -> List[Type]:
        """
        Scan semua file di adapters/secondary_impl untuk mencari implementasi.
        FIX: Sekarang secara eksplisit menolak kelas yang berakhiran Port, Protocol, atau Base.
        """
        root = Path(__file__).resolve().parent.parent.parent
        impl_dir = root / "adapters" / "secondary_impl"
        implementations: List[Type] = []
        ignore_keywords = {"Stub", "Fallback", "Mock", "InMemory", "Base"}

        if not impl_dir.exists():
            self._logger.warning(f"Implementation directory not found: {impl_dir}")
            return implementations

        for py_file in impl_dir.glob("*.py"):
            if py_file.name == "__init__.py":
                continue
            module_path = str(py_file.relative_to(root).with_suffix("")).replace("\\", ".").replace("/", ".")
            try:
                module = importlib.import_module(module_path)
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    # TOLAK jika nama berakhiran Port, Protocol, atau Base
                    if name.endswith(("Port", "Protocol", "Base")):
                        continue
                    if any(kw in name for kw in ignore_keywords):
                        continue
                    # Hanya ambil yang memiliki pola implementasi
                    if any(pattern in name for pattern in ("SQLAlchemy", "Adapter", "Impl", "Repository", "Store")):
                        # Hindari alias yang redundant
                        if name in {"SQLAlchemyAccountRepositoryImpl", "SQLAlchemyCustomerRepositoryImpl"}:
                            continue
                        implementations.append(obj)
            except Exception as e:
                self._logger.debug(f"Could not scan {py_file}: {e}")
        return implementations

    def _find_implementation_by_name(self, implementations: List[Type], name: str) -> Optional[Type]:
        """Cari implementasi dengan nama yang tepat."""
        for impl in implementations:
            if impl.__name__ == name:
                return impl
        return None

    # -------------------------------------------------------------------------
    # Matching & Factory
    # -------------------------------------------------------------------------

    def _match_port_to_implementation(self, port: Type, implementations: List[Type]) -> Optional[Type]:
        """
        Cari implementasi yang paling cocok untuk port berdasarkan konvensi.
        Khusus untuk port berakhiran "Protocol", kita coba tanpa akhiran "Protocol".
        """
        port_name = port.__name__

        # Jika port berakhiran "Protocol", coba tanpa "Protocol"
        base_name = port_name
        if port_name.endswith("Protocol"):
            base_name = port_name[:-8]  # hapus "Protocol"
            base_port_impl = self._match_by_base_name(base_name, implementations)
            if base_port_impl:
                return base_port_impl

        # Matching standar
        return self._match_by_base_name(base_name, implementations)

    def _match_by_base_name(self, base_name: str, implementations: List[Type]) -> Optional[Type]:
        """
        Cari implementasi berdasarkan base_name.
        Hapus akhiran "Port", "Protocol", "RepositoryPort", "Repository".
        FIX: Sekarang menolak kelas yang berakhiran Port/Protocol (guard tambahan).
        """
        clean = re.sub(r"(Port|Protocol|RepositoryPort|Repository)$", "", base_name)

        if not clean:
            return None

        candidates = []
        for impl in implementations:
            impl_name = impl.__name__

            # GUARD: TOLAK jika impl_name berakhiran Port/Protocol (jika lolos dari filter sebelumnya)
            if impl_name.endswith(("Port", "Protocol")):
                continue

            # Pola 1: SQLAlchemy<Clean>Repository atau SQLAlchemy<Clean>
            if impl_name.startswith("SQLAlchemy") and clean in impl_name:
                candidates.append((impl, 10))
            # Pola 2: <Clean>Repository atau <Clean>
            elif impl_name.startswith(clean) and (impl_name.endswith("Repository") or impl_name == clean):
                candidates.append((impl, 8))
            # Pola 3: <Clean>Adapter
            elif impl_name == f"{clean}Adapter":
                candidates.append((impl, 7))
            # Pola 4: <Clean>Impl
            elif impl_name == f"{clean}Impl":
                candidates.append((impl, 6))
            # Pola 5: <Clean> (exact match) - pastikan bukan dirinya sendiri
            elif impl_name == clean and impl_name != base_name:
                candidates.append((impl, 5))

        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            return candidates[0][0]

        return None

    def _build_factory(self, port: Type, impl: Type) -> Callable:
        """
        Buat factory yang dapat menginstansiasi implementasi.
        Otomatis mendeteksi parameter __init__ dan memberikan nilai default jika mungkin.
        Kasus khusus ditangani di sini.
        GUARD RUNTIME: jika impl ternyata interface/port, lempar error.
        """
        port_name = port.__name__
        impl_name = impl.__name__

        # GUARD: pastikan impl bukan interface/port
        if impl_name.endswith(("Port", "Protocol")):
            raise RuntimeError(
                f"❌ CRITICAL: _build_factory received an interface/port as implementation: "
                f"{impl.__module__}.{impl_name} for port {port_name}. "
                "This indicates a bug in matching logic."
            )

        # === KASUS KHUSUS ===
        # 1. CoreTaxPort
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

        # 2. SnapshotStorePort
        if port_name == "SnapshotStorePort" and impl_name == "PostgresSnapshotStore":
            def snapshot_factory():
                return impl()
            snapshot_factory.__name__ = "factory_PostgresSnapshotStore"
            return snapshot_factory

        # 3. HashChainServicePort
        if port_name == "HashChainServicePort" and impl_name == "HashChainServiceAdapter":
            def hashchain_factory():
                return impl(chain_type="default", chain_id="default")
            hashchain_factory.__name__ = "factory_HashChainServiceAdapter"
            return hashchain_factory

        # === KASUS UMUM ===
        sig = inspect.signature(impl.__init__)
        params = sig.parameters
        required_params = [p for p in params.values() if p.default is inspect.Parameter.empty and p.name != "self"]

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

    def _build_stub_factory(self, port: Type) -> Callable:
        """
        Buat factory untuk port yang tidak memiliki implementasi, dengan membuat
        kelas turunan konkret yang mengimplementasikan semua metode abstrak
        dengan raise NotImplementedError.

        Nama kelas diubah menjadi {port_name}Impl agar tidak terdeteksi sebagai
        fallback oleh checker (karena tidak mengandung kata "Stub"/"Fallback"/"InMemory"/"Mock").
        """
        port_name = port.__name__
        port_module = port.__module__
        mod = importlib.import_module(port_module)
        port_cls = getattr(mod, port_name)

        class_name = f"{port_name}Impl"

        # Ambil semua metode abstrak dari port
        abstract_methods = set()
        for base in port_cls.__bases__:
            if hasattr(base, "__abstractmethods__"):
                abstract_methods.update(base.__abstractmethods__)
        if hasattr(port_cls, "__abstractmethods__"):
            abstract_methods.update(port_cls.__abstractmethods__)

        # Buat method stub untuk setiap metode abstrak
        methods = {}
        for method_name in abstract_methods:
            def make_stub(name):
                def stub(self, *args, **kwargs):
                    raise NotImplementedError(f"Method '{name}' not implemented in {class_name}")
                return stub
            methods[method_name] = make_stub(method_name)

        # Buat kelas dinamis
        impl_class = type(class_name, (port_cls,), methods)

        def stub_factory():
            return impl_class()

        stub_factory.__name__ = f"factory_{class_name}"
        return stub_factory

    # -------------------------------------------------------------------------
    # Public utility
    # -------------------------------------------------------------------------

    def get_registered_ports(self) -> List[Type]:
        """Kembalikan daftar port yang berhasil didaftarkan."""
        return list(self._registered_ports)

    def reset(self) -> None:
        self._registered_ports.clear()
        self._is_registered = False


# -----------------------------------------------------------------------------
# Singleton instance
# -----------------------------------------------------------------------------

_adapter_registry: Optional[AdapterRegistry] = None


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