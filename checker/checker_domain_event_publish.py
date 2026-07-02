#!/usr/bin/env python3
"""
Sovereign ERP System - Domain Event Publish Checker (Full Data Flow + Advanced)
=====================================================================
Mendeteksi SEMUA event yang di-instantiate di seluruh project,
termasuk yang di-assign ke variabel, disimpan di _events, lalu dipublish.
Cross-check dengan registry (all_event_handlers.py).
Base events (abstract/framework) otomatis diabaikan.

Fitur tambahan (baru):
  - Location Check   : peringatan jika event dipublish di infrastructure/adapter/repository/migration
  - After Commit     : peringatan jika event dipublish setelah commit()/flush()
  - Order Check      : peringatan jika event dipublish sebelum ada perubahan state (assignment ke self.*)

Cara pakai:
  python checker/checker_domain_event_publish.py
  python checker/checker_domain_event_publish.py --json report.json
  python checker/checker_domain_event_publish.py --verbose
  python checker/checker_domain_event_publish.py --hide-dead
  python checker/checker_domain_event_publish.py --strict
  python checker/checker_domain_event_publish.py --check-location
  python checker/checker_domain_event_publish.py --check-commit
  python checker/checker_domain_event_publish.py --check-order
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

# =============================================================================
# Konfigurasi Root Project
# =============================================================================
ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# =============================================================================
# Konfigurasi Terminal
# =============================================================================
COLOR = {
    "RED": "\033[91m",
    "GREEN": "\033[92m",
    "YELLOW": "\033[93m",
    "BLUE": "\033[94m",
    "CYAN": "\033[96m",
    "BOLD": "\033[1m",
    "RESET": "\033[0m"
}
if not sys.stdout.isatty():
    COLOR = dict.fromkeys(COLOR, "")

EXCLUDED_DIRS = {
    "checker", "tests", "migrations", "__pycache__", ".git",
    "docs", "scripts", "deployment", "monitoring", "reports", "alembic"
}

PUBLISH_METHODS = {"publish", "add_event", "apply", "record_event", "emit", "raise_event", "append"}
DISPATCH_METHODS = {"dispatch", "put", "send", "notify", "trigger", "fire", "call"}

# Direktori yang tidak boleh digunakan untuk publish event (arsitektur)
FORBIDDEN_PUBLISH_DIRS = {"infrastructure", "adapters", "repositories", "migration"}

# Event yang dianggap sebagai base/abstract/framework, tidak perlu registrasi
BASE_EVENTS = {
    "Event",
    "DomainEvent",
    "IntegrationEvent",
    "EconomicEvent",
    "CanonicalEvent",
    "LifecycleEvent",
    "SovereigntyEvent",
    "QueuedEvent",
    "OutboxEvent",
    "DeadLetterEvent",
    "AfterReportingPeriodEvent",
    "_FallbackAuditEvent",
    "GoingConcernEvent",
    "BaseEvent",
}

IGNORE_EVENTS = BASE_EVENTS.union({
    # Event-event yang tidak perlu dicek karena base atau bukan domain
})

FALSE_POSITIVE_EVENTS = {
    "envelope", "record", "topic", "applied_by", "disclosure",
    "shutdown", "shutting_down", "shut_down", "timeout", "error", "warning"
}

# Event yang sengaja dipublish lebih dari 1 kali (berbeda konteks / service)
DUPLICATE_EXCEPTIONS = {
    # Period
    "PeriodOpenedEvent",
    "PeriodClosedEvent",
    "PeriodReopenedEvent",
    "PeriodStatusChangedEvent",
    # Journal
    "JournalPostedEvent",
    # Credit/Invoice
    "CreditNoteIssuedEvent",
    "InvoiceApprovedEvent",
    "InvoiceCancelledEvent",
    "InvoiceCreatedEvent",
    "InvoiceIssuedEvent",
    "InvoicePaidEvent",
    "InvoicePartiallyPaidEvent",
    "InvoiceDisputedEvent",
    "InvoiceVerifiedEvent",
    "InvoiceWrittenOffEvent",
    "InvoiceReceivedEvent",
    # Payment
    "PaymentVoidedEvent",
    "PaymentMadeEvent",
    "PaymentReceivedEvent",
    # Account (COA vs IAM)
    "AccountCreatedEvent",
    "AccountUpdatedEvent",
    "AccountDeactivatedEvent",
    "AccountReactivatedEvent",
    "AccountLockedEvent",
    "AccountUnlockedEvent",
    # Legal Entity
    "LegalEntityCreatedEvent",
    "LegalEntityUpdatedEvent",
    "LegalEntityDeactivatedEvent",
    "CompanySuspendedEvent",
    "CompanyReactivatedEvent",
    "CompanyDissolvedEvent",
    "CompanyRegisteredEvent",
    "CompanyAddressUpdatedEvent",
    "CompanyContactUpdatedEvent",
    # Fixed Asset vs Intangible Asset
    "AssetAcquiredEvent",
    "AssetDepreciationPostedEvent",
    "AssetDisposedEvent",
    "AssetImpairedEvent",
    "AssetFullyDepreciatedEvent",
    "AssetRevaluatedEvent",
    "AssetTransferredEvent",
    # Standard Cost
    "StandardCostCreatedEvent",
    "StandardCostActivatedEvent",
    # Tax
    "FakturSubmittedEvent",
    "FakturApprovedEvent",
    "FakturRejectedEvent",
    "SPTSubmittedEvent",
    "SPTApprovedEvent",
    "TaxCalculatedEvent",
    "TaxProfileUpdatedEvent",
    # Employee
    "EmployeeStructureUpdatedEvent",
    # User
    "UserPasswordChangedEvent",
    # Permission
    "PermissionGrantedEvent",
    "PermissionRevokedEvent",
    # Login
    "LoginFailureEvent",
    "LoginSuccessEvent",
    # Transaction
    "TransactionRecordedEvent",
    # Hierarchy
    "HierarchyChangedEvent",
    # Bupot
    "BupotSubmittedEvent",
    "BupotApprovedEvent",
    # Budget
    "BudgetApprovedEvent",
    "BudgetCancelledEvent",
    "BudgetClosedEvent",
    "BudgetCreatedEvent",
    "BudgetLineAddedEvent",
    "BudgetLineAdjustedEvent",
    "BudgetLineRemovedEvent",
    "BudgetRejectedEvent",
    "BudgetRevisedEvent",
    "BudgetStatusChangedEvent",
    "BudgetArchivedEvent",
    # Consolidation
    "ConsolidationCompletedEvent",
    "ConsolidationStartedEvent",
    "ConsolidationCancelledEvent",
    "ConsolidationArchivedEvent",
    "EliminationEntryCreatedEvent",
    "IntercompanyTransactionDetectedEvent",
    "NCICalculatedEvent",
    # Goodwill
    "GoodwillRecognizedEvent",
    "GoodwillAmortizedEvent",
    "GoodwillImpairedEvent",
    "GoodwillImpairmentReversedEvent",
    "GoodwillDisposedEvent",
    "GoodwillUpdatedEvent",
    # Hedge
    "HedgeDesignatedEvent",
    "HedgeDiscontinuedEvent",
    "HedgeEffectivenessTestedEvent",
    "HedgeAmountReclassifiedEvent",
    "HedgeCancelledEvent",
    "HedgeFairValueAdjustedEvent",
    # Cash
    "CashReceiptIssuedEvent",
    "CashReceiptConfirmedEvent",
    "CashReceiptCancelledEvent",
    "CashDisbursementIssuedEvent",
    "CashDisbursementApprovedEvent",
    "CashDisbursementPaidEvent",
    "CashDisbursementCancelledEvent",
    "PettyCashFundCreatedEvent",
    "PettyCashReplenishedEvent",
    "PettyCashDisbursementEvent",
    "PettyCashAdjustedEvent",
    "PettyCashClosedEvent",
    "PettyCashActivatedEvent",
    "PettyCashSuspendedEvent",
    "CashBookUpdatedEvent",
    "CashBookClosedEvent",
    # Bank
    "BankAccountCreatedEvent",
    "BankAccountUpdatedEvent",
    "BankAccountBlockedEvent",
    "BankAccountClosedEvent",
    "BankTransactionRecordedEvent",
    "BankTransactionClearedEvent",
    "BankTransactionReconciledEvent",
    "BankReconciliationCompletedEvent",
    "BankTransferInitiatedEvent",
    "BankTransferCompletedEvent",
    "BankTransferFailedEvent",
    "BankTransferCancelledEvent",
    "BankTransferExecutedEvent",
    # Other
    "CompanySuspendedEvent",
    "CompanyReactivatedEvent",
    "CompanyDissolvedEvent",
    "CompanyRegisteredEvent",
    "CompanyAddressUpdatedEvent",
    "CompanyContactUpdatedEvent",
    "MaterialIssuedEvent",
    "LaborPostedEvent",
    "OverheadAppliedEvent",
    "ProductionCompletedEvent",
    "HPPCalculatedEvent",
    "VarianceAnalyzedEvent",
    "CostCardUpdatedEvent",
    "RevenueRecognizedEvent",
    "ProjectBillingGeneratedEvent",
    "MilestoneReadyEvent",
    "MilestoneBilledEvent",
    "ProjectCreatedEvent",
    "ProjectActivatedEvent",
    "ProjectCompletedEvent",
    "TimeEntrySubmittedEvent",
    "TimeEntryApprovedEvent",
    "RetainerContractActivatedEvent",
    "ThreeWayMatchResultEvent",
    "PurchaseOrderCreatedEvent",
    "PurchaseOrderApprovedEvent",
    "PurchaseInvoiceReceivedEvent",
    "PurchaseInvoiceApprovedEvent",
    "PurchaseInvoicePaidEvent",
    "SalesOrderCreatedEvent",
    "SalesOrderApprovedEvent",
    "SalesInvoiceIssuedEvent",
    "SalesInvoicePaidEvent",
    "GoodsReceiptCreatedEvent",
    "DeliveryNoteShippedEvent",
    "PaymentApprovedEvent",
    "PaymentProcessedEvent",
    "PaymentConfirmedEvent",
    "PaymentSentEvent",
    "PaymentCancelledEvent",
    "PaymentAllocatedEvent",
    "PaymentAppliedEvent",
    "PeriodCreatedEvent",
    "PeriodUpdatedEvent",
    "PeriodLockedEvent",
    "COACreatedEvent",
    "COAArchivedEvent",
    "COALockedEvent",
    "COAUnlockedEvent",
    "JournalCreatedEvent",
    "JournalSubmittedEvent",
    "JournalApprovedEvent",
    "JournalRejectedEvent",
    "JournalReversedEvent",
    "JournalVoidedEvent",
    "JournalAdjustedEvent",
    "JournalArchivedEvent",
    "JournalUnarchivedEvent",
    "JournalCancelledEvent",
    "SettingAddedEvent",
    "SettingChangedEvent",
    "SettingRemovedEvent",
    "SettingResetEvent",
    "SettingsBulkUpdatedEvent",
    "SettingsLockedEvent",
    "SettingsUnlockedEvent",
    "UserCreatedEvent",
    "UserUpdatedEvent",
    "UserActivatedEvent",
    "UserDeactivatedEvent",
    "UserSuspendedEvent",
    "UserUnlockedEvent",
    "UserDeletedEvent",
    "RoleCreatedEvent",
    "RoleUpdatedEvent",
    "RoleDeletedEvent",
    "RoleAssignedEvent",
    "RoleRevokedEvent",
    "SessionCreatedEvent",
    "SessionRefreshedEvent",
    "SessionTerminatedEvent",
    "SessionCompromisedEvent",
    "MeteraiUsedEvent",
    "PKPStatusChangedEvent",
    "TaxProfileUpdatedEvent",
}

@dataclass
class EventUsage:
    event_name: str
    file_path: str
    line_no: int
    context: str

@dataclass
class EventInfo:
    event_name: str
    usages: list[EventUsage] = field(default_factory=list)

@dataclass
class Violation:
    severity: str  # ERROR / WARNING / INFO
    message: str
    detail: str = ""

class EventPublishChecker:
    def __init__(self, root_dir: pathlib.Path, strict: bool = False,
                 check_location: bool = False, check_commit: bool = False,
                 check_order: bool = False):
        self.root_dir = root_dir
        self.strict = strict
        self.check_location = check_location
        self.check_commit = check_commit
        self.check_order = check_order

        self.registry_events: set[str] = set()
        self.registry_events_norm: set[str] = set()
        self.event_classes: set[str] = set()
        self.instantiated_events: set[str] = set()
        self.base_events: set[str] = set()
        self.publish_counts: dict[str, int] = defaultdict(int)
        self.publish_locations: dict[str, list[tuple[str, int]]] = defaultdict(list)

    def _get_python_files(self, base_dir: pathlib.Path | None = None) -> list[pathlib.Path]:
        target = base_dir or self.root_dir
        py_files = []
        for p in target.rglob("*.py"):
            if any(part in EXCLUDED_DIRS for part in p.parts):
                continue
            if p.name.startswith(("test_", "conftest")):
                continue
            py_files.append(p)
        return py_files

    def _normalize_event_name(self, name: str) -> str:
        if name.endswith("Event"):
            return name[:-5]
        return name

    def _is_event_class_name(self, name: str) -> bool:
        if not name:
            return False
        if name in IGNORE_EVENTS:
            return False
        if name in FALSE_POSITIVE_EVENTS:
            return False
        return name.endswith("Event") and name not in IGNORE_EVENTS

    def load_registry_and_events(self):
        try:
            import application.events.all_event_handlers as all_handlers
            if hasattr(all_handlers, "register_all_handlers"):
                all_handlers.register_all_handlers()
                print(f"{COLOR['GREEN']}✅ register_all_handlers() dipanggil.{COLOR['RESET']}")
            from application.events.handler_registry import event_handler_registry
            registry = event_handler_registry
            for attr in ["_handlers", "handlers", "registry"]:
                if hasattr(registry, attr):
                    data = getattr(registry, attr)
                    if isinstance(data, dict):
                        for ev_type in data.keys():
                            ev_name = ev_type if isinstance(ev_type, str) else getattr(ev_type, "__name__", str(ev_type))
                            self.registry_events.add(ev_name)
                            self.registry_events_norm.add(self._normalize_event_name(ev_name))
                        break
            if not self.registry_events:
                if hasattr(all_handlers, "handlers") and isinstance(all_handlers.handlers, dict):
                    for ev_name in all_handlers.handlers.keys():
                        self.registry_events.add(ev_name)
                        self.registry_events_norm.add(self._normalize_event_name(ev_name))
            print(f"  Registry: {len(self.registry_events)} event terdaftar.")
        except Exception as e:
            print(f"{COLOR['YELLOW']}⚠ Gagal load registry: {e}{COLOR['RESET']}")

        domain_dir = self.root_dir / "domain"
        if domain_dir.exists():
            for py_file in domain_dir.rglob("*.py"):
                try:
                    src = py_file.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(src, filename=str(py_file))
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef) and self._is_event_class_name(node.name):
                            self.event_classes.add(node.name)
                except Exception:
                    pass
        print(f"  Event Classes: {len(self.event_classes)} ditemukan.")

    def scan_events(self) -> dict[str, EventInfo]:
        events_map: dict[str, EventInfo] = {}
        files = self._get_python_files()

        for py_file in files:
            try:
                src = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=str(py_file))
            except SyntaxError:
                continue

            rel_path = str(py_file.relative_to(self.root_dir))

            class EventTracker(ast.NodeVisitor):
                def __init__(self):
                    self.usages: list[EventUsage] = []
                    self.var_to_event: dict[str, str] = {}
                    self.attr_to_event: dict[str, str] = {}
                    self.list_to_event: dict[str, str] = {}
                    self.import_alias: dict[str, str] = {}
                    self.publish_calls: list[tuple[str, int]] = []   # (event_name, line_no)
                    self.commit_lines: list[int] = []                # baris commit/flush
                    self.assignment_lines: list[int] = []            # baris assignment ke self.* (non-event)

                def visit_Import(self, node):
                    for alias in node.names:
                        if alias.asname:
                            self.import_alias[alias.asname] = alias.name
                        else:
                            self.import_alias[alias.name.split('.')[-1]] = alias.name
                    self.generic_visit(node)

                def visit_ImportFrom(self, node):
                    module = node.module or ""
                    for alias in node.names:
                        full_name = f"{module}.{alias.name}" if module else alias.name
                        if alias.asname:
                            self.import_alias[alias.asname] = full_name
                        else:
                            self.import_alias[alias.name] = full_name
                    self.generic_visit(node)

                def resolve_name(self, name: str) -> str:
                    if name in self.import_alias:
                        original = self.import_alias[name]
                        return original.split('.')[-1]
                    return name

                def visit_Assign(self, node):
                    # Catat assignment ke self.* (untuk order check)
                    for target in node.targets:
                        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                            # abaikan jika assignment ke event (self._event, self.events)
                            if not target.attr.startswith("_") and target.attr not in ("event", "events"):
                                self.assignment_lines.append(node.lineno)

                    if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
                        event_name = node.value.func.id
                        if event_name in self.import_alias:
                            event_name = self.import_alias[event_name].split('.')[-1]
                        if self._is_event_class(event_name):
                            for target in node.targets:
                                if isinstance(target, ast.Name):
                                    self.var_to_event[target.id] = event_name
                                    self.usages.append(EventUsage(
                                        event_name=event_name,
                                        file_path=rel_path,
                                        line_no=node.lineno,
                                        context=f"assignment to variable '{target.id}'"
                                    ))
                                elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                                    self.attr_to_event[target.attr] = event_name
                                    self.usages.append(EventUsage(
                                        event_name=event_name,
                                        file_path=rel_path,
                                        line_no=node.lineno,
                                        context=f"assignment to self.{target.attr}"
                                    ))

                    elif isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute):
                        if node.value.func.attr == "append" and node.value.args:
                            arg = node.value.args[0]
                            event_name = None
                            if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
                                event_name = arg.func.id
                                if event_name in self.import_alias:
                                    event_name = self.import_alias[event_name].split('.')[-1]
                                if self._is_event_class(event_name):
                                    self.usages.append(EventUsage(
                                        event_name=event_name,
                                        file_path=rel_path,
                                        line_no=node.lineno,
                                        context="_events.append(SomeEvent(...))"
                                    ))
                            elif isinstance(arg, ast.Name) and arg.id in self.var_to_event:
                                event_name = self.var_to_event[arg.id]
                                self.usages.append(EventUsage(
                                    event_name=event_name,
                                    file_path=rel_path,
                                    line_no=node.lineno,
                                    context=f"append variable '{arg.id}' to list"
                                ))

                            if isinstance(node.value.func.value, ast.Name):
                                list_name = node.value.func.value.id
                                if event_name:
                                    self.list_to_event[list_name] = event_name

                    elif isinstance(node.value, ast.Name):
                        if node.value.id in self.var_to_event:
                            event_name = self.var_to_event[node.value.id]
                            for target in node.targets:
                                if isinstance(target, ast.Name):
                                    self.var_to_event[target.id] = event_name

                    elif isinstance(node.value, ast.List) and node.value.elts:
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Call) and isinstance(elt.func, ast.Name):
                                event_name = elt.func.id
                                if event_name in self.import_alias:
                                    event_name = self.import_alias[event_name].split('.')[-1]
                                if self._is_event_class(event_name):
                                    for target in node.targets:
                                        if isinstance(target, ast.Name):
                                            self.var_to_event[target.id] = event_name
                                            self.usages.append(EventUsage(
                                                event_name=event_name,
                                                file_path=rel_path,
                                                line_no=node.lineno,
                                                context=f"list assignment to '{target.id}'"
                                            ))
                    self.generic_visit(node)

                def visit_Call(self, node):
                    func = node.func
                    method_name = ""
                    is_publish = False

                    if isinstance(func, ast.Attribute) and func.attr in PUBLISH_METHODS:
                        is_publish = True
                        method_name = func.attr
                    elif isinstance(func, ast.Name) and func.id in PUBLISH_METHODS:
                        is_publish = True
                        method_name = func.id
                    elif isinstance(func, ast.Attribute) and func.attr in DISPATCH_METHODS:
                        is_publish = True
                        method_name = func.attr
                    elif isinstance(func, ast.Name) and func.id in DISPATCH_METHODS:
                        is_publish = True
                        method_name = func.id

                    # Catat commit/flush
                    if isinstance(func, ast.Attribute) and func.attr in ("commit", "flush"):
                        self.commit_lines.append(node.lineno)

                    if is_publish and node.args:
                        arg = node.args[0]
                        event_name = None

                        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
                            event_name = arg.func.id
                            if event_name in self.import_alias:
                                event_name = self.import_alias[event_name].split('.')[-1]
                            if self._is_event_class(event_name):
                                self.usages.append(EventUsage(
                                    event_name=event_name,
                                    file_path=rel_path,
                                    line_no=node.lineno,
                                    context=f"publish call ({method_name})"
                                ))
                                self.publish_calls.append((event_name, node.lineno))

                        elif isinstance(arg, ast.Name):
                            if arg.id in self.var_to_event:
                                event_name = self.var_to_event[arg.id]
                                self.usages.append(EventUsage(
                                    event_name=event_name,
                                    file_path=rel_path,
                                    line_no=node.lineno,
                                    context=f"publish variable '{arg.id}' via {method_name}"
                                ))
                                self.publish_calls.append((event_name, node.lineno))
                            elif arg.id in self.list_to_event:
                                event_name = self.list_to_event[arg.id]
                                self.usages.append(EventUsage(
                                    event_name=event_name,
                                    file_path=rel_path,
                                    line_no=node.lineno,
                                    context=f"publish list '{arg.id}' via {method_name}"
                                ))
                                self.publish_calls.append((event_name, node.lineno))

                        elif isinstance(arg, ast.Attribute):
                            if arg.attr in self.attr_to_event:
                                event_name = self.attr_to_event[arg.attr]
                                self.usages.append(EventUsage(
                                    event_name=event_name,
                                    file_path=rel_path,
                                    line_no=node.lineno,
                                    context=f"publish self.{arg.attr}"
                                ))
                                self.publish_calls.append((event_name, node.lineno))

                    if isinstance(node.func, ast.Name) and node.func.id == "return":
                        for arg in node.args:
                            if isinstance(arg, ast.List) and arg.elts:
                                for elt in arg.elts:
                                    if isinstance(elt, ast.Call) and isinstance(elt.func, ast.Name):
                                        event_name = elt.func.id
                                        if event_name in self.import_alias:
                                            event_name = self.import_alias[event_name].split('.')[-1]
                                        if self._is_event_class(event_name):
                                            self.usages.append(EventUsage(
                                                event_name=event_name,
                                                file_path=rel_path,
                                                line_no=node.lineno,
                                                context="return [SomeEvent(...)]"
                                            ))
                    self.generic_visit(node)

                def visit_Yield(self, node):
                    if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
                        event_name = node.value.func.id
                        if event_name in self.import_alias:
                            event_name = self.import_alias[event_name].split('.')[-1]
                        if self._is_event_class(event_name):
                            self.usages.append(EventUsage(
                                event_name=event_name,
                                file_path=rel_path,
                                line_no=node.lineno,
                                context="yield SomeEvent(...)"
                            ))
                    self.generic_visit(node)

                def _is_event_class(self, name: str) -> bool:
                    return name.endswith("Event") and name not in IGNORE_EVENTS and name not in FALSE_POSITIVE_EVENTS

            tracker = EventTracker()
            try:
                tracker.visit(tree)
            except Exception:
                continue

            # Simpan publish calls untuk duplicate & lokasi
            for ev_name, line in tracker.publish_calls:
                self.publish_counts[ev_name] += 1
                self.publish_locations[ev_name].append((rel_path, line))

            # Simpan usages
            for usage in tracker.usages:
                if usage.event_name in BASE_EVENTS:
                    self.base_events.add(usage.event_name)
                    continue
                if usage.event_name not in events_map:
                    events_map[usage.event_name] = EventInfo(event_name=usage.event_name)
                events_map[usage.event_name].usages.append(usage)
                self.instantiated_events.add(usage.event_name)

            # ---- FITUR TAMBAHAN ----
            # 1. Location check: cek apakah file berada di direktori terlarang
            if self.check_location:
                for ev_name, line in tracker.publish_calls:
                    if any(forbidden in rel_path.split("/") for forbidden in FORBIDDEN_PUBLISH_DIRS):
                        # tambahkan violation nanti di check()
                        # kita simpan di struktur tambahan
                        if not hasattr(self, "_location_violations"):
                            self._location_violations = []
                        self._location_violations.append((ev_name, rel_path, line))

            # 2. After commit check: apakah ada commit sebelum publish
            if self.check_commit and tracker.commit_lines:
                for ev_name, line in tracker.publish_calls:
                    if any(commit_line < line for commit_line in tracker.commit_lines):
                        if not hasattr(self, "_commit_violations"):
                            self._commit_violations = []
                        self._commit_violations.append((ev_name, rel_path, line))

            # 3. Order check: apakah publish sebelum ada assignment ke self.*
            if self.check_order and tracker.assignment_lines:
                for ev_name, line in tracker.publish_calls:
                    # Jika tidak ada assignment sebelum publish, atau assignment setelah publish
                    # maka dianggap order salah
                    # Cari assignment terdekat sebelum publish
                    prev_assign = max((a for a in tracker.assignment_lines if a < line), default=None)
                    if prev_assign is None:
                        if not hasattr(self, "_order_violations"):
                            self._order_violations = []
                        self._order_violations.append((ev_name, rel_path, line))

        return events_map

    def check(self) -> tuple[dict[str, EventInfo], list[Violation]]:
        self.load_registry_and_events()
        events_map = self.scan_events()

        violations = []

        # 1. Registry validation
        for ev_name, info in events_map.items():
            norm = self._normalize_event_name(ev_name)
            if ev_name not in self.registry_events and norm not in self.registry_events_norm:
                is_domain_event = ev_name in self.event_classes
                if self.strict:
                    severity = "ERROR"
                else:
                    severity = "ERROR" if is_domain_event else "WARNING"
                detail = "\n".join(
                    f"    - {u.file_path}:{u.line_no} ({u.context})" for u in info.usages
                )
                violations.append(Violation(
                    severity=severity,
                    message=f"Event '{ev_name}' digunakan tetapi tidak terdaftar di registry." +
                            (f" (domain event)" if is_domain_event else " (non-domain/base event)"),
                    detail=detail
                ))

        # 2. Dead Event Detection (INFO)
        used_events = set(events_map.keys())
        registered_not_used = set()
        for ev in self.registry_events:
            if ev in BASE_EVENTS:
                continue
            norm = self._normalize_event_name(ev)
            if ev not in used_events and norm not in used_events:
                if ev in self.event_classes or norm in self.event_classes:
                    registered_not_used.add(ev)

        for ev in registered_not_used:
            violations.append(Violation(
                severity="INFO",
                message=f"Event '{ev}' terdaftar di registry tetapi TIDAK PERNAH digunakan/dipublish.",
                detail="Event ini mungkin dead code atau belum digunakan."
            ))

        # 3. Duplicate Publish Detection
        for ev_name, count in self.publish_counts.items():
            if count > 1 and ev_name not in DUPLICATE_EXCEPTIONS:
                locations = "\n".join(
                    f"    - {path}:{line}" for path, line in self.publish_locations[ev_name][:5]
                )
                if len(self.publish_locations[ev_name]) > 5:
                    locations += f"\n    ... and {len(self.publish_locations[ev_name]) - 5} more"
                violations.append(Violation(
                    severity="WARNING",
                    message=f"Event '{ev_name}' dipublish {count} kali (kemungkinan duplicate publish).",
                    detail=locations
                ))

        # 4. Location violations
        if self.check_location and hasattr(self, "_location_violations"):
            for ev_name, path, line in self._location_violations:
                violations.append(Violation(
                    severity="WARNING",
                    message=f"Event '{ev_name}' dipublish di lokasi terlarang: {path}:{line}",
                    detail="Publish event sebaiknya hanya di layer domain/service, bukan di infrastructure/adapter/repository/migration."
                ))

        # 5. After commit violations
        if self.check_commit and hasattr(self, "_commit_violations"):
            for ev_name, path, line in self._commit_violations:
                violations.append(Violation(
                    severity="WARNING",
                    message=f"Event '{ev_name}' dipublish setelah commit/flush di {path}:{line}",
                    detail="Publish event sebaiknya dilakukan sebelum commit untuk memastikan konsistensi transaksional."
                ))

        # 6. Order violations
        if self.check_order and hasattr(self, "_order_violations"):
            for ev_name, path, line in self._order_violations:
                violations.append(Violation(
                    severity="WARNING",
                    message=f"Event '{ev_name}' dipublish sebelum ada perubahan state aggregate di {path}:{line}",
                    detail="Event seharusnya dipublish setelah aggregate berubah (assignment ke self.*)."
                ))

        return events_map, violations

def main():
    parser = argparse.ArgumentParser(description="Domain Event Publish Checker (Full Data Flow + Advanced)")
    parser.add_argument("--json", metavar="FILE", help="Ekspor laporan ke JSON")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail tambahan")
    parser.add_argument("--strict", action="store_true", help="Perlakukan semua event tidak terdaftar sebagai ERROR")
    parser.add_argument("--hide-dead", action="store_true", help="Sembunyikan INFO (dead event) dari laporan")
    parser.add_argument("--quiet", action="store_true", help="Hanya tampilkan ringkasan")
    # Fitur baru
    parser.add_argument("--check-location", action="store_true", help="Deteksi publish di infrastructure/adapter/repository/migration")
    parser.add_argument("--check-commit", action="store_true", help="Deteksi publish setelah commit/flush")
    parser.add_argument("--check-order", action="store_true", help="Deteksi publish sebelum aggregate berubah")
    args = parser.parse_args()

    start_time = time.monotonic()
    root_dir = ROOT
    checker = EventPublishChecker(
        root_dir,
        strict=args.strict,
        check_location=args.check_location,
        check_commit=args.check_commit,
        check_order=args.check_order
    )

    print(f"{COLOR['BOLD']}{COLOR['CYAN']}╔════════════════════════════════════════════════════════════════════╗")
    print("║    SOVEREIGN DOMAIN EVENT PUBLISH CHECKER (ADVANCED)           ║")
    print(f"╚════════════════════════════════════════════════════════════════════╝{COLOR['RESET']}")
    print(f"  Mode Deteksi             :  {COLOR['GREEN']}✅ Data Flow + Alias + Container{COLOR['RESET']}")
    print(f"  Tracking Assignment      :  {COLOR['GREEN']}✅ event = SomeEvent(...){COLOR['RESET']}")
    print(f"  Tracking self._event     :  {COLOR['GREEN']}✅ self._event = SomeEvent(...){COLOR['RESET']}")
    print(f"  Tracking _events.append :  {COLOR['GREEN']}✅ self._events.append(SomeEvent(...)){COLOR['RESET']}")
    print(f"  Tracking yield/return   :  {COLOR['GREEN']}✅ yield/return SomeEvent(...){COLOR['RESET']}")
    print(f"  Tracking dispatch/emit  :  {COLOR['GREEN']}✅ dispatch/emit SomeEvent(...){COLOR['RESET']}")
    print(f"  Import Alias Resolution  :  {COLOR['GREEN']}✅ import X as Y{COLOR['RESET']}")
    print(f"  Container Flow           :  {COLOR['GREEN']}✅ list.append -> publish(list){COLOR['RESET']}")
    print(f"  Duplicate Detect         :  {COLOR['GREEN']}✅ Multiple publish warnings (dengan pengecualian){COLOR['RESET']}")
    print(f"  Dead Event Detect        :  {COLOR['GREEN']}✅ Registry but never used{COLOR['RESET']}")
    if args.hide_dead:
        print(f"  Hide Dead Events         :  {COLOR['YELLOW']}✅ INFO violations hidden{COLOR['RESET']}")
    print(f"  Source of Truth          :  {COLOR['CYAN']}Registry from all_event_handlers.py{COLOR['RESET']}")
    if args.strict:
        print(f"  Mode Strict              :  {COLOR['RED']}✅ Semua event tidak terdaftar = ERROR{COLOR['RESET']}")
    else:
        print(f"  Mode Strict              :  {COLOR['YELLOW']}❌ Domain event = ERROR, Base event = WARNING{COLOR['RESET']}")

    if args.check_location:
        print(f"  Check Location           :  {COLOR['GREEN']}✅ Aktif (forbidden dirs: {', '.join(FORBIDDEN_PUBLISH_DIRS)}){COLOR['RESET']}")
    if args.check_commit:
        print(f"  Check After Commit       :  {COLOR['GREEN']}✅ Aktif{COLOR['RESET']}")
    if args.check_order:
        print(f"  Check Order              :  {COLOR['GREEN']}✅ Aktif (publish sebelum state change){COLOR['RESET']}")

    events_map, violations = checker.check()

    if args.hide_dead:
        violations = [v for v in violations if v.severity != "INFO"]

    total_events = len(events_map)
    error_count = sum(1 for v in violations if v.severity == "ERROR")
    warning_count = sum(1 for v in violations if v.severity == "WARNING")
    info_count = sum(1 for v in violations if v.severity == "INFO")
    score = max(0, 100 - (error_count * 2) - (warning_count * 1) - (info_count * 0)) if total_events > 0 else 100

    if not args.quiet:
        print(f"\n  Total Event Digunakan    :  {total_events}")
        print(f"  ✅ Terdaftar di Registry :  {total_events - error_count}")
        print(f"  ❌ Tidak Terdaftar       :  {COLOR['RED'] if error_count > 0 else COLOR['GREEN']}{error_count} ERROR{COLOR['RESET']}, {COLOR['YELLOW']}{warning_count} WARNING{COLOR['RESET']}, {COLOR['BLUE']}{info_count} INFO{COLOR['RESET']}")
        print(f"  📈 Skor Kepatuhan        :  {COLOR['CYAN']}{COLOR['BOLD']}{score}/100{COLOR['RESET']}")

        used_concrete = len(events_map)
        total_domain = len(checker.event_classes)
        unused = max(0, total_domain - used_concrete)

        print(f"\n{COLOR['BOLD']}─── STATISTICS ───{COLOR['RESET']}")
        print(f"  Registry Entries          :  {len(checker.registry_events)}")
        print(f"  Domain Event Classes      :  {total_domain}")
        print(f"  Used Concrete Events      :  {used_concrete}")
        print(f"  Unused Domain Events      :  {unused}")
        if used_concrete > 0:
            avg = len(checker.registry_events) / used_concrete
            print(f"  Avg Handlers per Event   :  {avg:.2f}")
        if checker.base_events:
            print(f"  Skipped Base Events      :  {len(checker.base_events)} (detected and skipped)")
        else:
            print(f"  Skipped Base Events      :  None detected")

        duplicates = {k: v for k, v in checker.publish_counts.items() if v > 1}
        if duplicates:
            print(f"  Duplicate Publish Events :  {len(duplicates)} (warnings shown below)")

    if violations and not args.quiet:
        print(f"\n{COLOR['BOLD']}─── DETAIL VIOLATIONS ───{COLOR['RESET']}")
        display_limit = 30 if not args.verbose else 200
        for v in violations[:display_limit]:
            color = COLOR["RED"] if v.severity == "ERROR" else COLOR["YELLOW"] if v.severity == "WARNING" else COLOR["BLUE"]
            print(f"  {color}[{v.severity}]{COLOR['RESET']} {v.message}")
            if v.detail and (args.verbose or v.severity != "INFO"):
                print(f"      {v.detail}")
        if len(violations) > display_limit:
            print(f"  ... and {len(violations)-display_limit} more violations. Use --verbose to see all.")
    elif not args.quiet:
        print(f"\n{COLOR['GREEN']}✅ Semua event yang digunakan terdaftar di registry.{COLOR['RESET']}")

    if args.verbose and events_map and not args.quiet:
        print(f"\n{COLOR['BOLD']}─── USED EVENTS ───{COLOR['RESET']}")
        for ev_name, info in sorted(events_map.items()):
            is_registered = ev_name in checker.registry_events or checker._normalize_event_name(ev_name) in checker.registry_events_norm
            is_domain = ev_name in checker.event_classes
            dup_count = checker.publish_counts.get(ev_name, 0)
            dup_marker = f" (dup:{dup_count})" if dup_count > 1 else ""
            if is_registered:
                status = "✅"
                color = COLOR["GREEN"]
            elif is_domain:
                status = "❌"
                color = COLOR["RED"]
            else:
                status = "⚠️"
                color = COLOR["YELLOW"]
            print(f"  {color}{status}{COLOR['RESET']} {ev_name}{dup_marker} (ditemukan di {len(info.usages)} lokasi)")

    if args.verbose and checker.base_events and not args.quiet:
        print(f"\n{COLOR['BOLD']}─── SKIPPED BASE EVENTS ───{COLOR['RESET']}")
        for ev in sorted(checker.base_events):
            print(f"  {COLOR['BLUE']}🔵{COLOR['RESET']} {ev}")

    if not args.quiet:
        print(f"\n ⏱️ Waktu Audit: {time.monotonic() - start_time:.3f} detik")

    if args.json:
        payload = {
            "total_used": total_events,
            "registered": total_events - error_count,
            "unregistered_error": error_count,
            "unregistered_warning": warning_count,
            "info": info_count,
            "score": score,
            "statistics": {
                "registry_entries": len(checker.registry_events),
                "domain_event_classes": len(checker.event_classes),
                "used_concrete_events": used_concrete,
                "unused_domain_events": unused,
                "skipped_base_events": len(checker.base_events),
                "duplicate_publish_events": len(duplicates),
            },
            "violations": [
                {"severity": v.severity, "message": v.message, "detail": v.detail}
                for v in violations
            ],
            "used_events": {
                ev: [{"file": u.file_path, "line": u.line_no, "context": u.context}
                     for u in info.usages]
                for ev, info in events_map.items()
            }
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        if not args.quiet:
            print(f"{COLOR['GREEN']}✅ Laporan diekspor ke {args.json}{COLOR['RESET']}")

    sys.exit(0 if error_count == 0 else 1)

if __name__ == "__main__":
    main()