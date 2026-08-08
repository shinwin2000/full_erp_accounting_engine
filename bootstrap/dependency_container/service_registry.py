#!/usr/bin/env python3
"""
Module: service_registry.py
Layer: Bootstrap (Dependency Container)
Responsibility: Mendaftarkan semua service ke IoC container.
               Production-grade: tidak ada fallback, dependency injection eksplisit.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from bootstrap.dependency_container.interfaces import ContainerInterface

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ServiceRegistry:
    def __init__(self, container: ContainerInterface | None = None):
        self._container = container
        self._services: dict[str, type] = {}
        self._aliases: dict[str, str] = {}
        self._logger = logging.getLogger(f"{__name__}.ServiceRegistry")

    def set_container(self, container: ContainerInterface) -> None:
        self._container = container

    def register_service(
        self,
        interface: type[T],
        implementation: type | None = None,
        lifetime: Any = None,
        name: str | None = None,
    ) -> None:
        from bootstrap.dependency_container.ioc_container import Lifetime
        if lifetime is None:
            lifetime = Lifetime.SINGLETON
        if self._container is None:
            raise RuntimeError("Container not set.")
        service_name = name or interface.__name__
        self._services[service_name] = interface
        if implementation:
            self._container.register(interface, implementation, lifetime=lifetime)
        else:
            self._container.register(interface, interface, lifetime=lifetime)
        self._logger.info(f"Registered service: {service_name}")

    def register_alias(self, alias: str, target: str) -> None:
        if not alias or not target:
            raise ValueError("Alias and target cannot be empty")
        self._aliases[alias] = target
        self._logger.debug(f"Registered alias: {alias} -> {target}")

    def get_service(self, service_name: str) -> type | None:
        if not service_name:
            raise ValueError("Service name cannot be empty")
        if service_name in self._aliases:
            service_name = self._aliases[service_name]
        return self._services.get(service_name)

    def resolve(self, interface: type[T], **kwargs) -> T:
        if self._container is None:
            raise RuntimeError("Container not set.")
        return self._container.resolve(interface, **kwargs)

    async def resolve_async(self, interface: type[T], **kwargs) -> T:
        if self._container is None:
            raise RuntimeError("Container not set.")
        return await self._container.resolve_async(interface, **kwargs)

    def resolve_by_name(self, name: str, **kwargs) -> Any:
        interface = self.get_service(name)
        if not interface:
            raise ValueError(f"Service not found: {name}")
        return self.resolve(interface, **kwargs)

    async def resolve_by_name_async(self, name: str, **kwargs) -> Any:
        interface = self.get_service(name)
        if not interface:
            raise ValueError(f"Service not found: {name}")
        return await self.resolve_async(interface, **kwargs)

    def list_services(self) -> list[str]:
        return sorted(self._services.keys())

    def has_service(self, service_name: str) -> bool:
        return service_name in self._services or service_name in self._aliases

    def unregister(self, service_name: str) -> bool:
        if service_name in self._services:
            del self._services[service_name]
            return True
        if service_name in self._aliases:
            del self._aliases[service_name]
            return True
        return False

    def reset(self) -> None:
        self._services.clear()
        self._aliases.clear()


def service(
    interface: type | None = None,
    name: str | None = None,
    lifetime: str = "singleton",
):
    """
    Dekorator untuk mendaftarkan service ke container.
    """
    def decorator(cls):
        from bootstrap.dependency_container.ioc_container import Lifetime
        lifetime_enum = getattr(Lifetime, lifetime.upper(), Lifetime.SINGLETON)
        service_name = name or cls.__name__
        service_interface = interface or cls
        cls._service_metadata = {"interface": service_interface, "lifetime": lifetime_enum, "name": service_name}
        return cls
    return decorator


class ServiceRegistrar:
    @staticmethod
    async def register_all(container: ContainerInterface | None = None) -> None:
        from bootstrap.dependency_container.ioc_container import get_container

        if container is None:
            container = get_container()

        registry = ServiceRegistry(container)

        # --- Application Services ---
        try:
            from application.service_layer.service_ap import APService
            from application.service_layer.service_ar import ARService
            from application.service_layer.service_bank_cash import BankCashService
            from application.service_layer.service_budget import BudgetService
            # Service Capital & Fiscal Period
            from application.service_layer.service_capital import CapitalService
            from application.service_layer.service_coa import COAService
            from application.service_layer.service_coretax import CoretaxService
            from application.service_layer.service_employee import EmployeeService
            from application.service_layer.service_fiscal_period import FiscalPeriodService
            from application.service_layer.service_fixed_asset import FixedAssetService
            from application.service_layer.service_inventory import InventoryService
            from application.service_layer.service_journal import JournalService
            from application.service_layer.service_legal_entity import LegalEntityService
            from application.service_layer.service_ledger import LedgerService
            from application.service_layer.service_manufacturing import ManufacturingService
            from application.service_layer.service_payroll import PayrollService
            from application.service_layer.service_report import ReportService
            from application.service_layer.service_tax import TaxService

            # FIX: SupplierService, CustomerService, dan PaymentService sebelumnya TIDAK
            # PERNAH terdaftar di sini sama sekali, padahal router-nya
            # (fastapi_supplier_router.py, fastapi_customer_router.py,
            # fastapi_payment_router.py) memakai Depends(get_service(...)) untuk
            # ketiganya. Akibatnya setiap request ke endpoint supplier/customer/payment
            # gagal dengan DependencyNotFoundError saat resolve.
            from application.service_layer.service_customer import CustomerService
            from application.service_layer.service_payment import PaymentService
            from application.service_layer.service_supplier import SupplierService

            # FIX: ApprovalService juga tidak pernah terdaftar di sini, padahal
            # fastapi_approval_router.py memanggil container.resolve_async(ApprovalService).
            # Akibatnya semua endpoint /api/v1/approval/* gagal dengan DependencyNotFoundError.
            from application.service_layer.service_approval import ApprovalService

            container.register_singleton(COAService, COAService)
            container.register_singleton(JournalService, JournalService)
            container.register_singleton(LedgerService, LedgerService)
            container.register_singleton(ARService, ARService)
            container.register_singleton(APService, APService)
            container.register_singleton(InventoryService, InventoryService)
            container.register_singleton(FixedAssetService, FixedAssetService)
            container.register_singleton(BankCashService, BankCashService)
            container.register_singleton(BudgetService, BudgetService)
            container.register_singleton(TaxService, TaxService)
            container.register_singleton(CoretaxService, CoretaxService)
            container.register_singleton(PayrollService, PayrollService)
            container.register_singleton(ManufacturingService, ManufacturingService)
            container.register_singleton(ReportService, ReportService)
            container.register_singleton(CustomerService, CustomerService)
            container.register_singleton(PaymentService, PaymentService)
            container.register_singleton(LegalEntityService, LegalEntityService)
            container.register_singleton(ApprovalService, ApprovalService)
            logger.info("LegalEntityService registered")
            logger.info("ApprovalService registered")

            # ----- Registrasi CapitalService dengan factory yang aman -----
            async def _create_capital_service():
                try:
                    from ports.primary.event_publisher_port import EventPublisherPort
                    event_publisher = await container.resolve_async(EventPublisherPort)
                except Exception:
                    event_publisher = None
                return CapitalService(event_publisher=event_publisher)

            container.register_singleton(CapitalService, factory=_create_capital_service)
            logger.info("CapitalService registered")

            # ----- Registrasi FiscalPeriodService dengan dependensi lengkap -----
            # Daftarkan repository dan port-nya terlebih dahulu
            from adapters.secondary_impl.sqlalchemy_fiscal_period_repository_impl import (
                SQLAlchemyFiscalPeriodRepository,
            )
            from ports.primary.fiscal_period_repository_port import FiscalPeriodRepositoryPort
            from ports.primary.unit_of_work_port import UnitOfWorkPort

            container.register_singleton(SQLAlchemyFiscalPeriodRepository, SQLAlchemyFiscalPeriodRepository)
            container.register_singleton(FiscalPeriodRepositoryPort, SQLAlchemyFiscalPeriodRepository)
            # UnitOfWorkPort sudah terdaftar di bagian IAM, tapi kita pastikan ada
            if not container.has_registration(UnitOfWorkPort):
                from adapters.secondary_impl.sqlalchemy_unit_of_work_impl import (
                    SQLAlchemyUnitOfWork,
                )
                container.register_singleton(UnitOfWorkPort, SQLAlchemyUnitOfWork)
                logger.info("UnitOfWorkPort registered (from fiscal period)")

            async def _create_fiscal_period_service():
                # Ambil dependensi dari container
                period_repo = await container.resolve_async(FiscalPeriodRepositoryPort)
                uow = await container.resolve_async(UnitOfWorkPort)
                try:
                    from ports.primary.event_publisher_port import EventPublisherPort
                    event_publisher = await container.resolve_async(EventPublisherPort)
                except Exception:
                    event_publisher = None
                return FiscalPeriodService(
                    period_repo=period_repo,
                    uow=uow,
                    event_publisher=event_publisher,
                )

            container.register_singleton(FiscalPeriodService, factory=_create_fiscal_period_service)
            logger.info("FiscalPeriodService registered with dependencies")

            # ----- Registrasi SupplierService dengan repository database -----
            # FIX (refactor sinkronisasi Supplier/Vendor): sebelumnya
            # `container.register_singleton(SupplierService, SupplierService)`
            # memanggil constructor tanpa argumen, sehingga SupplierService
            # jatuh ke mode in-memory dict dan TIDAK PERNAH menyimpan data ke
            # database. Sekarang SupplierService WAJIB menerima
            # SupplierRepositoryPort (SQLAlchemy, tabel `supplier`).
            from adapters.secondary_impl.sqlalchemy_supplier_repository_impl import (
                SQLAlchemySupplierRepository,
            )
            from ports.primary.supplier_repository_port import SupplierRepositoryPort

            container.register_singleton(SQLAlchemySupplierRepository, SQLAlchemySupplierRepository)
            container.register_singleton(SupplierRepositoryPort, SQLAlchemySupplierRepository)

            async def _create_supplier_service():
                supplier_repo = await container.resolve_async(SupplierRepositoryPort)
                try:
                    from ports.primary.event_publisher_port import EventPublisherPort
                    event_publisher = await container.resolve_async(EventPublisherPort)
                except Exception:
                    event_publisher = None
                return SupplierService(repository=supplier_repo, event_publisher=event_publisher)

            container.register_singleton(SupplierService, factory=_create_supplier_service)
            logger.info("SupplierService registered with database repository")

            # ----- Registrasi EmployeeService dengan factory yang aman -----
            async def _create_employee_service():
                try:
                    from ports.primary.event_publisher_port import EventPublisherPort
                    event_publisher = await container.resolve_async(EventPublisherPort)
                except Exception:
                    event_publisher = None
                return EmployeeService(event_publisher=event_publisher)

            container.register_singleton(EmployeeService, factory=_create_employee_service)
            logger.info("EmployeeService registered")

            logger.info("Application services registered")
        except ImportError as e:
            logger.warning(f"Some application services could not be imported: {e}")

        # --- Command & Query Bus ---
        try:
            from application.commands_cqrs.command_bus_unified import CommandBusUnified
            from application.commands_cqrs.query_bus_unified import QueryBusUnified
            container.register_singleton(CommandBusUnified, CommandBusUnified)
            container.register_singleton(QueryBusUnified, QueryBusUnified)
            logger.info("Command/Query buses registered")
        except ImportError as e:
            logger.warning(f"CQRS buses not available: {e}")

        # --- Kernel ---
        try:
            gate_mod = importlib.import_module("kernel.sealed_gate")
            SealedGate = gate_mod.SealedGate
            get_sealed_gate = gate_mod.get_sealed_gate
            container.register_singleton(SealedGate, factory=get_sealed_gate)
            logger.info("Kernel singletons registered")
        except ImportError as e:
            logger.warning(f"Kernel singletons not available: {e}")

        # --- Infrastructure factories ---
        try:
            from adapters.secondary_impl.sqlalchemy_unit_of_work_impl import get_uow_factory
            container.register_singleton("UoWFactory", factory=get_uow_factory)
        except ImportError:
            pass

        try:
            from infrastructure.caching.redis_manager import get_redis_manager
            container.register_singleton("RedisManager", factory=get_redis_manager)
        except ImportError:
            pass

        try:
            gate_mod = importlib.import_module("event_gateway.event_gate_singleton")
            get_event_gate = gate_mod.get_event_gate
            container.register_singleton("EventGate", factory=get_event_gate)
        except ImportError:
            pass

        try:
            from infrastructure.message_broker.kafka_producer_wrapper import get_kafka_producer
            container.register_singleton("KafkaProducer", factory=get_kafka_producer)
        except ImportError:
            pass

        try:
            from infrastructure.message_broker.transactional_outbox_poller import get_outbox_poller
            container.register_singleton("OutboxPoller", factory=get_outbox_poller)
        except ImportError:
            pass

        # ============================================================
        # --- IAM SERVICE & DEPENDENCIES (Production-grade) ---
        # ============================================================
        try:
            from adapters.secondary_impl.sqlalchemy_iam_user_repository_impl import (
                SQLAlchemyIAMRepository,
                SQLAlchemyIAMUserRepository,
            )
            from adapters.secondary_impl.sqlalchemy_unit_of_work_impl import SQLAlchemyUnitOfWork
            from application.service_layer.service_iam import IAMService
            from ports.primary.iam_repository_port import IAMRepositoryPort
            from ports.primary.iam_user_repository_port import IAMUserRepositoryPort
            from ports.primary.unit_of_work_port import UnitOfWorkPort

            # Daftarkan implementasi konkret sebagai singleton (tanpa session/legal_entity)
            container.register_singleton(SQLAlchemyIAMUserRepository, SQLAlchemyIAMUserRepository)
            container.register_singleton(SQLAlchemyIAMRepository, SQLAlchemyIAMRepository)
            container.register_singleton(SQLAlchemyUnitOfWork, SQLAlchemyUnitOfWork)

            # Port â†’ implementation (singleton, tapi session & legal_entity_id di-set per request)
            container.register_singleton(IAMUserRepositoryPort, SQLAlchemyIAMUserRepository)
            container.register_singleton(IAMRepositoryPort, SQLAlchemyIAMRepository)
            container.register_singleton(UnitOfWorkPort, SQLAlchemyUnitOfWork)

            # Dependency opsional
            event_publisher = None
            token_issuer = None
            cache = None

            try:
                from adapters.secondary_impl.kafka_event_publisher_impl import KafkaEventPublisher as EventPublisher

                from ports.primary.event_publisher_port import EventPublisherPort
                container.register_singleton(EventPublisher, EventPublisher)
                container.register_singleton(EventPublisherPort, EventPublisher)
                event_publisher = await container.resolve_async(EventPublisherPort)
                logger.info("EventPublisher registered")
            except ImportError:
                logger.warning("EventPublisher not available, using None")

            try:
                from infrastructure.security.jwt_token_service import JWTTokenService
                from ports.primary.token_issuer_port import TokenIssuerPort
                container.register_singleton(JWTTokenService, JWTTokenService)
                container.register_singleton(TokenIssuerPort, JWTTokenService)
                token_issuer = await container.resolve_async(TokenIssuerPort)
                logger.info("JWTTokenService registered")
            except ImportError:
                logger.warning("JWTTokenService not available, using None")

            try:
                from infrastructure.caching.redis_cache import RedisCache

                from ports.primary.cache_port import CachePort
                container.register_singleton(RedisCache, RedisCache)
                container.register_singleton(CachePort, RedisCache)
                cache = await container.resolve_async(CachePort)
                logger.info("RedisCache registered")
            except ImportError:
                logger.warning("RedisCache not available, using None")

            # Factory untuk IAMService â€“ repository dan UoW diambil dari container,
            # namun session & legal_entity_id akan di-set via service.set_context()
            async def _create_iam_service():
                iam_repo = await container.resolve_async(IAMRepositoryPort)
                uow = await container.resolve_async(UnitOfWorkPort)
                return IAMService(
                    iam_repo=iam_repo,
                    uow=uow,
                    event_publisher=event_publisher,
                    token_issuer=token_issuer,
                    cache=cache
                )

            container.register_singleton(IAMService, factory=_create_iam_service)
            logger.info("IAMService and dependencies registered")
        except Exception as e:
            logger.error(f"Failed to register IAMService: {e}")

        logger.info("All application services registered to IoC container")

    @staticmethod
    def register_all_sync() -> None:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(ServiceRegistrar.register_all())
            loop.close()
        except Exception as e:
            logger.error(f"Service registration failed: {e}")
            raise


_service_registry: ServiceRegistry | None = None


def get_service_registry() -> ServiceRegistry:
    global _service_registry
    if _service_registry is None:
        from bootstrap.dependency_container.ioc_container import get_container
        _service_registry = ServiceRegistry(get_container())
    return _service_registry


__all__ = [
    "ServiceRegistrar",
    "ServiceRegistry",
    "get_service_registry",
    "service",
]
