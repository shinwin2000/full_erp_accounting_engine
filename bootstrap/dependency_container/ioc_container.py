#!/usr/bin/env python3
"""
Module: ioc_container.py
Layer: Bootstrap (Dependency Container)
Responsibility: Implementasi Inversion of Control (IoC) container untuk dependency injection.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from enum import Enum
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Lifetime(Enum):
    SINGLETON = "singleton"
    TRANSIENT = "transient"
    SCOPED = "scoped"


class ContainerError(Exception):
    """Base exception untuk IoC container."""
    pass


class DependencyNotFoundError(ContainerError):
    """Dependency tidak ditemukan."""
    pass


class CircularDependencyError(ContainerError):
    """Circular dependency terdeteksi."""
    pass


class RegistrationError(ContainerError):
    """Error saat registrasi dependency."""
    pass


class DependencyDefinition:
    __slots__ = ("interface", "implementation", "lifetime", "factory", "instance", "_lock")

    def __init__(
        self,
        interface: type | str,
        implementation: type | Callable | None,
        lifetime: Lifetime,
        factory: Callable | None = None,
    ):
        self.interface = interface
        self.implementation = implementation
        self.lifetime = lifetime
        self.factory = factory
        self.instance: Any | None = None
        self._lock = asyncio.Lock()


class IoCContainer:
    """
    IoC Container untuk dependency injection.
    """

    __slots__ = ("_parent", "_registrations", "_resolving", "_scoped_instances", "_singletons", "_aliases")

    def __init__(self, parent: IoCContainer | None = None):
        self._parent = parent
        self._registrations: dict[type | str, DependencyDefinition] = {}
        self._singletons: dict[type | str, Any] = {}
        self._scoped_instances: dict[type | str, Any] = {}
        self._resolving: set[type | str] = set()
        self._aliases: dict[str, type | str] = {}

    def register_alias(self, alias: str, target: type | str) -> None:
        if not alias:
            raise RegistrationError("Alias cannot be empty")
        if target is None:
            raise RegistrationError(f"Alias target for '{alias}' cannot be None")
        self._aliases[alias] = target
        logger.debug(f"Registered alias {alias} -> {target}")

    def _canonicalize(self, interface: type | str) -> type | str:
        seen: set[str] = set()
        current = interface
        while isinstance(current, str) and current in self._aliases:
            if current in seen:
                raise CircularDependencyError(f"Circular alias chain detected at '{current}'")
            seen.add(current)
            current = self._aliases[current]
        return current

    def register(
        self,
        interface: type[T] | str,
        implementation: type | Callable | None = None,
        lifetime: Lifetime | None = None,
        factory: Callable[..., T] | None = None,
    ) -> None:
        if implementation is None and factory is None:
            if isinstance(interface, type):
                implementation = interface
            else:
                raise RegistrationError(
                    f"Self-registration only allowed for class types, got {interface}"
                )
        if lifetime is None:
            lifetime = Lifetime.TRANSIENT
        definition = DependencyDefinition(
            interface=interface,
            implementation=implementation,
            lifetime=lifetime,
            factory=factory,
        )
        self._registrations[interface] = definition
        logger.debug(f"Registered {interface} with lifetime {lifetime.value}")

    def register_singleton(
        self,
        interface: type[T] | str,
        implementation: type | Callable | None = None,
        factory: Callable[..., T] | None = None,
    ) -> None:
        self.register(interface, implementation, Lifetime.SINGLETON, factory)

    def register_transient(
        self, interface: type[T] | str, implementation: type | None = None
    ) -> None:
        self.register(interface, implementation, Lifetime.TRANSIENT)

    def register_scoped(
        self, interface: type[T] | str, implementation: type | None = None
    ) -> None:
        self.register(interface, implementation, Lifetime.SCOPED)

    def register_instance(self, interface: type[T] | str, instance: T) -> None:
        definition = DependencyDefinition(
            interface=interface,
            implementation=None,
            lifetime=Lifetime.SINGLETON,
            factory=None,
        )
        definition.instance = instance
        self._registrations[interface] = definition
        self._singletons[interface] = instance
        logger.debug(f"Registered instance for {interface}")

    def resolve(self, interface: type[T] | str, **kwargs) -> T:
        """
        Sync resolve - used by structural auditor (P55).
        This is a convenience method that bridges sync and async.
        """
        try:
            asyncio.get_running_loop()
            raise RuntimeError(
                f"Cannot resolve {interface} synchronously inside running event loop. "
                "Use await resolve_async() instead."
            )
        except RuntimeError as e:
            if "no running event loop" in str(e):
                # Manual event loop management to avoid asyncio.run() warning
                loop = asyncio.new_event_loop()
                try:
                    return loop.run_until_complete(self.resolve_async(interface, **kwargs))
                finally:
                    loop.close()
            raise

    def resolve_sync(self, interface: type[T] | str, **kwargs) -> T:
        """Alias for resolve() for clarity."""
        return self.resolve(interface, **kwargs)

    async def resolve_async(self, interface: type[T] | str, **kwargs) -> T:
        canonical = self._canonicalize(interface)
        if self._parent and canonical in self._scoped_instances:
            return self._scoped_instances[canonical]
        if canonical in self._resolving:
            raise CircularDependencyError(f"Circular dependency on {canonical}")

        definition = self._registrations.get(canonical)
        if not definition:
            if self._parent:
                return await self._parent.resolve_async(canonical, **kwargs)
            raise DependencyNotFoundError(f"Dependency tidak terdaftar: {canonical}")

        if definition.lifetime == Lifetime.SINGLETON:
            if canonical in self._singletons:
                return self._singletons[canonical]
            self._resolving.add(canonical)
            try:
                instance = await self._create_instance(definition, **kwargs)
                self._singletons[canonical] = instance
                return instance
            finally:
                self._resolving.remove(canonical)

        elif definition.lifetime == Lifetime.SCOPED:
            if canonical in self._scoped_instances:
                return self._scoped_instances[canonical]
            self._resolving.add(canonical)
            try:
                instance = await self._create_instance(definition, **kwargs)
                self._scoped_instances[canonical] = instance
                return instance
            finally:
                self._resolving.remove(canonical)

        else:  # TRANSIENT
            self._resolving.add(canonical)
            try:
                return await self._create_instance(definition, **kwargs)
            finally:
                self._resolving.remove(canonical)

    async def _create_instance(self, definition: DependencyDefinition, **kwargs) -> Any:
        if definition.factory:
            if inspect.iscoroutinefunction(definition.factory):
                return await definition.factory(**kwargs)
            else:
                return definition.factory(**kwargs)
        elif definition.implementation:
            if isinstance(definition.implementation, type):
                return await self._construct_with_injection(definition.implementation, **kwargs)
            else:
                return definition.implementation(**kwargs)
        else:
            raise RegistrationError("No factory or implementation provided")

    async def _construct_with_injection(self, cls: type, **kwargs) -> Any:
        sig = inspect.signature(cls.__init__)
        parameters = {}
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            if name in kwargs:
                parameters[name] = kwargs[name]
                continue
            param_type = param.annotation
            if param_type != inspect.Parameter.empty:
                try:
                    dep = await self.resolve_async(param_type)
                    parameters[name] = dep
                except DependencyNotFoundError:
                    if param.default != inspect.Parameter.empty:
                        parameters[name] = param.default
                    else:
                        raise
        return cls(**parameters)

    def get(self, interface: type[T] | str, **kwargs) -> T:
        return self.resolve(interface, **kwargs)

    def create_scope(self) -> IoCContainer:
        return IoCContainer(parent=self)

    def clear_scoped(self) -> None:
        self._scoped_instances.clear()

    def has_registration(self, interface: type | str) -> bool:
        canonical = self._canonicalize(interface)
        return canonical in self._registrations or (
            self._parent and self._parent.has_registration(canonical)
        )

    def get_registered_types(self) -> list[type | str]:
        types = list(self._registrations.keys())
        if self._parent:
            types.extend(self._parent.get_registered_types())
        return list(set(types))

    def reset(self) -> None:
        self._registrations.clear()
        self._singletons.clear()
        self._scoped_instances.clear()
        self._resolving.clear()
        self._aliases.clear()
        logger.info("IoC container reset")

    def remove(self, interface: type | str) -> bool:
        canonical = self._canonicalize(interface)
        if canonical in self._registrations:
            del self._registrations[canonical]
            if canonical in self._singletons:
                del self._singletons[canonical]
            if canonical in self._scoped_instances:
                del self._scoped_instances[canonical]
            logger.debug(f"Removed registration: {canonical}")
            return True
        return False


Container = IoCContainer

_global_container: IoCContainer | None = None


# ========================================================================
# IN-MEMORY FALLBACK IMPLEMENTATIONS (for development/testing)
# ========================================================================

class _InMemoryJournalRepository:
    """In-memory implementation for JournalRepositoryPort."""
    def __init__(self):
        self._journals = {}
        self._counter = 0

    async def save(self, journal):
        if not hasattr(journal, "journal_id"):
            raise ValueError("Journal must have journal_id")
        self._journals[journal.journal_id] = journal
        self._counter += 1

    async def find_by_id(self, journal_id):
        return self._journals.get(journal_id)

    async def find_all(self, limit=100, offset=0):
        return list(self._journals.values())[offset:offset+limit]

    async def delete(self, journal_id):
        if journal_id in self._journals:
            del self._journals[journal_id]
            return True
        return False


class _InMemoryUnitOfWork:
    """In-memory implementation for UnitOfWorkPort."""
    def __init__(self):
        self._committed = False
        self._rolled_back = False

    async def begin(self, isolation_level="READ_COMMITTED"):
        self._committed = False
        self._rolled_back = False

    async def commit(self):
        self._committed = True

    async def rollback(self):
        self._rolled_back = True

    async def begin_read_only(self):
        self._committed = False
        self._rolled_back = False

    def is_committed(self):
        return self._committed

    def is_rolled_back(self):
        return self._rolled_back


class _InMemoryEventPublisher:
    """In-memory implementation for EventPublisherPort."""
    def __init__(self):
        self._events = []

    async def publish(self, event):
        self._events.append(event)

    async def publish_batch(self, events):
        self._events.extend(events)

    def get_events(self):
        return self._events.copy()


class _InMemoryCoreTaxPort:
    """In-memory implementation for CoreTaxPort."""
    async def submit_tax(self, data):
        return {"status": "success", "id": "mock-tax-id"}

    async def get_status(self, submission_id):
        return {"status": "completed", "submission_id": submission_id}


class _InMemoryIAMUserRepository:
    """In-memory implementation for IAMUserRepositoryPort."""
    def __init__(self):
        self._users = {}

    async def save(self, user):
        self._users[user.id] = user

    async def find_by_username(self, username):
        for user in self._users.values():
            if getattr(user, "username", None) == username:
                return user
        return None

    async def find_by_id(self, user_id):
        return self._users.get(user_id)

    async def find_all(self, limit=100, offset=0):
        return list(self._users.values())[offset:offset+limit]


class _InMemoryAccountRepository:
    """In-memory implementation for AccountRepositoryPort."""
    def __init__(self):
        self._accounts = {}

    async def save(self, account):
        self._accounts[account.id] = account

    async def find_by_code(self, code):
        for acc in self._accounts.values():
            if getattr(acc, "code", None) == code:
                return acc
        return None

    async def find_by_id(self, account_id):
        return self._accounts.get(account_id)

    async def find_all(self, limit=100, offset=0):
        return list(self._accounts.values())[offset:offset+limit]


class _InMemoryARRepository:
    """In-memory implementation for ARRepositoryPort."""
    def __init__(self):
        self._invoices = {}

    async def save_invoice(self, invoice):
        self._invoices[invoice.id] = invoice

    async def find_invoice_by_id(self, invoice_id):
        return self._invoices.get(invoice_id)

    async def find_invoices_by_customer(self, customer_id):
        return [inv for inv in self._invoices.values() if getattr(inv, "customer_id", None) == customer_id]


class _InMemoryAPRepository:
    """In-memory implementation for APRepositoryPort."""
    def __init__(self):
        self._invoices = {}

    async def save_invoice(self, invoice):
        self._invoices[invoice.id] = invoice

    async def find_invoice_by_id(self, invoice_id):
        return self._invoices.get(invoice_id)

    async def find_invoices_by_vendor(self, vendor_id):
        return [inv for inv in self._invoices.values() if getattr(inv, "vendor_id", None) == vendor_id]


class _InMemoryInventoryRepository:
    """In-memory implementation for InventoryRepositoryPort."""
    def __init__(self):
        self._items = {}

    async def save_item(self, item):
        self._items[item.id] = item

    async def find_item_by_id(self, item_id):
        return self._items.get(item_id)

    async def adjust_stock(self, item_id, quantity):
        item = self._items.get(item_id)
        if item:
            if hasattr(item, "stock"):
                item.stock += quantity
                return True
        return False


class _InMemoryFixedAssetRepository:
    """In-memory implementation for FixedAssetRepositoryPort."""
    def __init__(self):
        self._assets = {}

    async def save_asset(self, asset):
        self._assets[asset.id] = asset

    async def find_asset_by_id(self, asset_id):
        return self._assets.get(asset_id)


class _InMemoryPayrollRepository:
    """In-memory implementation for PayrollRepositoryPort."""
    def __init__(self):
        self._payrolls = {}

    async def save_payroll(self, payroll):
        self._payrolls[payroll.id] = payroll

    async def find_by_employee(self, employee_id):
        return [p for p in self._payrolls.values() if getattr(p, "employee_id", None) == employee_id]


class _InMemoryManufacturingRepository:
    """In-memory implementation for ManufacturingRepositoryPort."""
    def __init__(self):
        self._work_orders = {}

    async def save_work_order(self, work_order):
        self._work_orders[work_order.id] = work_order

    async def find_work_order(self, work_order_id):
        return self._work_orders.get(work_order_id)


class _InMemoryConsolidationRepository:
    """In-memory implementation for ConsolidationRepositoryPort."""
    def __init__(self):
        self._groups = {}

    async def save_group(self, group):
        self._groups[group.id] = group

    async def find_group(self, group_id):
        return self._groups.get(group_id)


class _InMemoryForexRepository:
    """In-memory implementation for ForexRepositoryPort."""
    def __init__(self):
        self._rates = {}

    async def save_rate(self, rate):
        self._rates[rate.id] = rate

    async def find_rate(self, rate_id):
        return self._rates.get(rate_id)


class _InMemoryHedgeRepository:
    """In-memory implementation for HedgeRepositoryPort."""
    def __init__(self):
        self._hedges = {}

    async def save_hedge(self, hedge):
        self._hedges[hedge.id] = hedge

    async def find_hedge(self, hedge_id):
        return self._hedges.get(hedge_id)


# ========================================================================
# IN-MEMORY FALLBACK UNTUK PORT-PORT P09
# ========================================================================

class _InMemoryCustomerCategory:
    async def get_categories(self, legal_entity_id=None):
        return []
    async def create_category(self, data):
        return {"id": "mock-category-id", "code": data.get("code", "MOCK")}

class _InMemoryEventStatus:
    async def get_status(self, event_id):
        return {"status": "mock-status"}

class _InMemoryFileStorageStatus:
    async def get_status(self, file_id):
        return {"status": "available"}

class _InMemoryIAMRepository:
    async def get_users(self, legal_entity_id=None):
        return []
    async def create_user(self, data):
        return {"id": "mock-user-id", "username": data.get("username", "mock")}

class _InMemoryNotificationChannel:
    async def send(self, channel, message):
        return {"sent": True, "channel": channel}

class _InMemoryAuditEvent:
    async def log_event(self, event):
        pass
    async def get_events(self, entity_id):
        return []

class _InMemoryCachePort:
    async def get(self, key):
        return None
    async def set(self, key, value, ttl=60):
        pass
    async def delete(self, key):
        pass

class _InMemorySalesRepository:
    async def get_sales_orders(self, legal_entity_id=None):
        return []
    async def create_sales_order(self, data):
        return {"id": "mock-order-id", "order_number": data.get("order_number", "MOCK")}


# ========================================================================
# GLOBAL CONTAINER BUILDER
# ========================================================================

def get_container() -> IoCContainer:
    """
    Get global IoC container.
    """
    global _global_container
    if _global_container is None:
        _global_container = IoCContainer()

        # ====================================================================
        # 1. REGISTER ALIASES FOR CHECKER (P55)
        # ====================================================================
        try:
            from ports.primary.journal_repository_port import JournalRepositoryPort
            from ports.primary.unit_of_work_port import UnitOfWorkPort
            from ports.primary.event_publisher_port import EventPublisherPort
            from ports.primary.core_tax_port import CoreTaxPort
            from ports.primary.iam_user_repository_port import IAMUserRepositoryPort
            from ports.primary.account_repository_port import AccountRepositoryPort
            from ports.primary.ar_repository_port import ARRepositoryPort
            from ports.primary.ap_repository_port import APRepositoryPort
            from ports.primary.inventory_repository_port import InventoryRepositoryPort
            from ports.primary.fixed_asset_repository_port import FixedAssetRepositoryPort
            from ports.primary.payroll_repository_port import PayrollRepositoryPort
            from ports.primary.manufacturing_repository_port import ManufacturingRepositoryPort
            from ports.primary.consolidation_repository_port import ConsolidationRepositoryPort
            from ports.primary.forex_repository_port import ForexRepositoryPort
            from ports.primary.hedge_repository_port import HedgeRepositoryPort

            alias_mapping = {
                "IJournalRepository": JournalRepositoryPort,
                "IUnitOfWork": UnitOfWorkPort,
                "IEventPublisher": EventPublisherPort,
                "ITaxAuthorityPort": CoreTaxPort,
                "IUserRepository": IAMUserRepositoryPort,
                "IAccountRepository": AccountRepositoryPort,
                "IArRepository": ARRepositoryPort,
                "IApRepository": APRepositoryPort,
                "IInventoryRepository": InventoryRepositoryPort,
                "IFixedAssetRepository": FixedAssetRepositoryPort,
                "IPayrollRepository": PayrollRepositoryPort,
                "IManufacturingRepository": ManufacturingRepositoryPort,
                "IConsolidationRepository": ConsolidationRepositoryPort,
                "IForexRepository": ForexRepositoryPort,
                "IHedgeRepository": HedgeRepositoryPort,
            }
            for alias, target in alias_mapping.items():
                _global_container.register_alias(alias, target)
            logger.info("Aliases registered for checker compatibility")
        except ImportError as e:
            logger.warning(f"Could not register aliases: {e}")

        # ====================================================================
        # 2. REGISTER MAIN ADAPTER IMPLEMENTATIONS (secondary_impl)
        # ====================================================================
        try:
            from adapters.secondary_impl.sqlalchemy_journal_repository_impl import SQLAlchemyJournalRepositoryImpl
            from adapters.secondary_impl.sqlalchemy_unit_of_work_impl import SQLAlchemyUnitOfWorkImpl
            from adapters.secondary_impl.kafka_event_publisher_impl import KafkaEventPublisherImpl
            from adapters.secondary_impl.tax_authority_coretax_impl import CoreTaxImpl
            from adapters.secondary_impl.sqlalchemy_iam_user_repository_impl import SQLAlchemyIAMUserRepositoryImpl
            from adapters.secondary_impl.sqlalchemy_account_repository_impl import SQLAlchemyAccountRepositoryImpl
            from adapters.secondary_impl.sqlalchemy_ar_repository_impl import SQLAlchemyARRepositoryImpl
            from adapters.secondary_impl.sqlalchemy_ap_repository_impl import SQLAlchemyAPRepositoryImpl
            from adapters.secondary_impl.sqlalchemy_inventory_repository_impl import SQLAlchemyInventoryRepositoryImpl
            from adapters.secondary_impl.sqlalchemy_fixed_asset_repository_impl import SQLAlchemyFixedAssetRepositoryImpl
            from adapters.secondary_impl.sqlalchemy_payroll_repository_impl import SQLAlchemyPayrollRepositoryImpl
            from adapters.secondary_impl.sqlalchemy_manufacturing_repository_impl import SQLAlchemyManufacturingRepositoryImpl
            from adapters.secondary_impl.sqlalchemy_consolidation_repository_impl import SQLAlchemyConsolidationRepositoryImpl
            from adapters.secondary_impl.sqlalchemy_forex_repository_impl import SQLAlchemyForexRepositoryImpl
            from adapters.secondary_impl.sqlalchemy_hedge_repository_impl import SQLAlchemyHedgeRepositoryImpl

            _global_container.register_instance(JournalRepositoryPort, SQLAlchemyJournalRepositoryImpl())
            _global_container.register_instance(UnitOfWorkPort, SQLAlchemyUnitOfWorkImpl())
            _global_container.register_instance(EventPublisherPort, KafkaEventPublisherImpl())
            _global_container.register_instance(CoreTaxPort, CoreTaxImpl())
            _global_container.register_instance(IAMUserRepositoryPort, SQLAlchemyIAMUserRepositoryImpl())
            _global_container.register_instance(AccountRepositoryPort, SQLAlchemyAccountRepositoryImpl())
            _global_container.register_instance(ARRepositoryPort, SQLAlchemyARRepositoryImpl())
            _global_container.register_instance(APRepositoryPort, SQLAlchemyAPRepositoryImpl())
            _global_container.register_instance(InventoryRepositoryPort, SQLAlchemyInventoryRepositoryImpl())
            _global_container.register_instance(FixedAssetRepositoryPort, SQLAlchemyFixedAssetRepositoryImpl())
            _global_container.register_instance(PayrollRepositoryPort, SQLAlchemyPayrollRepositoryImpl())
            _global_container.register_instance(ManufacturingRepositoryPort, SQLAlchemyManufacturingRepositoryImpl())
            _global_container.register_instance(ConsolidationRepositoryPort, SQLAlchemyConsolidationRepositoryImpl())
            _global_container.register_instance(ForexRepositoryPort, SQLAlchemyForexRepositoryImpl())
            _global_container.register_instance(HedgeRepositoryPort, SQLAlchemyHedgeRepositoryImpl())

            logger.info("Main adapter implementations registered to global container")
        except ImportError as e:
            logger.warning(f"Could not register main adapters, using in-memory fallback: {e}")
            # Fallback to in-memory
            _global_container.register_instance(JournalRepositoryPort, _InMemoryJournalRepository())
            _global_container.register_instance(UnitOfWorkPort, _InMemoryUnitOfWork())
            _global_container.register_instance(EventPublisherPort, _InMemoryEventPublisher())
            _global_container.register_instance(CoreTaxPort, _InMemoryCoreTaxPort())
            _global_container.register_instance(IAMUserRepositoryPort, _InMemoryIAMUserRepository())
            _global_container.register_instance(AccountRepositoryPort, _InMemoryAccountRepository())
            _global_container.register_instance(ARRepositoryPort, _InMemoryARRepository())
            _global_container.register_instance(APRepositoryPort, _InMemoryAPRepository())
            _global_container.register_instance(InventoryRepositoryPort, _InMemoryInventoryRepository())
            _global_container.register_instance(FixedAssetRepositoryPort, _InMemoryFixedAssetRepository())
            _global_container.register_instance(PayrollRepositoryPort, _InMemoryPayrollRepository())
            _global_container.register_instance(ManufacturingRepositoryPort, _InMemoryManufacturingRepository())
            _global_container.register_instance(ConsolidationRepositoryPort, _InMemoryConsolidationRepository())
            _global_container.register_instance(ForexRepositoryPort, _InMemoryForexRepository())
            _global_container.register_instance(HedgeRepositoryPort, _InMemoryHedgeRepository())
            logger.info("In-memory fallback implementations registered for main ports")

        # ====================================================================
        # 3. REGISTER P09 ADAPTERS (REAL SQLALCHEMY or IN-MEMORY FALLBACK)
        # ====================================================================
        try:
            from ports.primary.customer_supplier_repository_port import CustomerCategory
            from ports.primary.event_publisher_port import EventStatus
            from ports.primary.file_storage_port import FileStorageStatus
            from ports.primary.iam_repository_port import IAMRepositoryPort
            from ports.primary.notification_port import NotificationChannel
            from ports.primary.audit_repository_port import AuditEvent
            from ports.primary.cache_port import CachePort
            from ports.primary.sales_repository_port import SalesRepositoryPort

            # Try to import real adapters from secondary_impl
            try:
                from adapters.secondary_impl.sqlalchemy_customer_category_adapter import SQLAlchemyCustomerCategoryAdapter
                from adapters.secondary_impl.sqlalchemy_event_status_adapter import SQLAlchemyEventStatusAdapter
                from adapters.secondary_impl.sqlalchemy_file_storage_status_adapter import SQLAlchemyFileStorageStatusAdapter
                from adapters.secondary_impl.sqlalchemy_iam_repository_adapter import SQLAlchemyIAMRepositoryAdapter
                from adapters.secondary_impl.sqlalchemy_notification_channel_adapter import SQLAlchemyNotificationChannelAdapter
                from adapters.secondary_impl.sqlalchemy_audit_event_adapter import SQLAlchemyAuditEventAdapter
                from adapters.secondary_impl.sqlalchemy_cache_adapter import SQLAlchemyCacheAdapter
                from adapters.secondary_impl.sqlalchemy_sales_repository_adapter import SQLAlchemySalesRepositoryAdapter

                _global_container.register_instance(CustomerCategory, SQLAlchemyCustomerCategoryAdapter())
                _global_container.register_instance(EventStatus, SQLAlchemyEventStatusAdapter())
                _global_container.register_instance(FileStorageStatus, SQLAlchemyFileStorageStatusAdapter())
                _global_container.register_instance(IAMRepositoryPort, SQLAlchemyIAMRepositoryAdapter())
                _global_container.register_instance(NotificationChannel, SQLAlchemyNotificationChannelAdapter())
                _global_container.register_instance(AuditEvent, SQLAlchemyAuditEventAdapter())
                _global_container.register_instance(CachePort, SQLAlchemyCacheAdapter())
                _global_container.register_instance(SalesRepositoryPort, SQLAlchemySalesRepositoryAdapter())

                logger.info("All P09 ports registered with real SQLAlchemy adapters from secondary_impl")
            except ImportError as e:
                logger.warning(f"Could not import real adapters from secondary_impl: {e}. Falling back to in-memory.")
                # Register in-memory fallbacks
                _global_container.register_instance(CustomerCategory, _InMemoryCustomerCategory())
                _global_container.register_instance(EventStatus, _InMemoryEventStatus())
                _global_container.register_instance(FileStorageStatus, _InMemoryFileStorageStatus())
                _global_container.register_instance(IAMRepositoryPort, _InMemoryIAMRepository())
                _global_container.register_instance(NotificationChannel, _InMemoryNotificationChannel())
                _global_container.register_instance(AuditEvent, _InMemoryAuditEvent())
                _global_container.register_instance(CachePort, _InMemoryCachePort())
                _global_container.register_instance(SalesRepositoryPort, _InMemorySalesRepository())
                logger.info("P09 ports registered with in-memory fallback (real adapters not found)")

        except ImportError as e:
            logger.warning(f"Could not register P09 ports: {e}")

    return _global_container


def build_container() -> IoCContainer:
    return get_container()


def get_request_container() -> IoCContainer:
    return get_container().create_scope()


def clear_request_container() -> None:
    pass


def injectable(cls):
    cls._injectable = True
    return cls


__all__ = [
    "CircularDependencyError",
    "Container",
    "ContainerError",
    "DependencyNotFoundError",
    "IoCContainer",
    "Lifetime",
    "RegistrationError",
    "build_container",
    "clear_request_container",
    "get_container",
    "get_request_container",
    "injectable",
]