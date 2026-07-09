# ports/primary/__init__.py
from __future__ import annotations

"""Package ports.primary - Antarmuka (abstraksi) untuk use case dan repository.

Layer ini mendefinisikan port yang diimplementasikan oleh adapter (primary dan secondary).
Semua port bersifat abstract base class atau protocol.
"""

from .account_repository_port import AccountRepositoryPort
from .ap_repository_port import APRepositoryPort
from .ar_repository_port import ARRepositoryPort
from .bank_cash_repository_port import BankAccountRepositoryPort, CashBookRepositoryPort
from .bank_statement_import_port import BankStatementImportPort
from .customer_repository_port import CustomerRepositoryPort
from .supplier_repository_port import SupplierRepositoryPort
from .employee_repository_port import EmployeeRepositoryPort
from .encryption_key_vault_port import EncryptionKeyVaultPort
from .event_publisher_port import EventPublisherPort
from .file_storage_port import FileStoragePort
from .fixed_asset_repository_port import FixedAssetRepositoryPort
from .hash_chain_service_port import HashChainServicePort
from .iam_user_repository_port import IAMUserRepositoryPort
from .inventory_repository_port import InventoryRepositoryPort
from .journal_repository_port import JournalRepositoryPort
from .ledger_repository_port import LedgerRepositoryPort
from .legal_entity_repository_port import LegalEntityRepositoryPort
from .notification_port import NotificationPort
from .system_setting_repository_port import SystemSettingRepositoryPort
from .tax_authority_coretax_port import TaxAuthorityCoretaxPort as CoreTaxPort
from .tax_transaction_repository_port import TaxTransactionRepositoryPort
from .timestamp_notary_port import TimestampNotaryPort
from .unit_of_work_port import RepositoryProvider, UnitOfWorkPort, get_uow

__all__ = [
    "APRepositoryPort",
    "ARRepositoryPort",
    "AccountRepositoryPort",
    "BankAccountRepositoryPort",
    "BankStatementImportPort",
    "CashBookRepositoryPort",
    "CoreTaxPort",
    "CustomerRepositoryPort",
    "EmployeeRepositoryPort",
    "EncryptionKeyVaultPort",
    "EventPublisherPort",
    "FileStoragePort",
    "FixedAssetRepositoryPort",
    "HashChainServicePort",
    "IAMUserRepositoryPort",
    "InventoryRepositoryPort",
    "JournalRepositoryPort",
    "LedgerRepositoryPort",
    "LegalEntityRepositoryPort",
    "NotificationPort",
    "RepositoryProvider",
    "SupplierRepositoryPort",
    "SystemSettingRepositoryPort",
    "TaxTransactionRepositoryPort",
    "TimestampNotaryPort",
    "UnitOfWorkPort",
    "get_uow",
]
