#!/usr/bin/env python3
"""
rca_project_rules.py — Project-Specific RCA Rules
====================================================
Modul ini mendaftarkan rule RCA yang TAHU PERSIS struktur proyek
full_erp_accounting_engine. Setiap rule dibangun dari exception class nyata,
nama file nyata, dan pola error nyata yang ada di proyek ini.

Integrasi: Import modul ini lalu panggil register_all(engine) untuk
           mendaftarkan semua rule project-specific ke RCAEngine.

Penggunaan:
    from checker.core.rca import get_engine
    from checker.core.rca_project_rules import register_all, self_test_project

    register_all(get_engine())     # sekali saat startup
    self_test_project()            # validasi semua rule berfungsi

Versi : 1.0.0
Standar: Real-world integration · Big 4 Forensic Audit
"""

from __future__ import annotations

import logging
import re
import sys

# ── Import base classes dari rca.py yang sudah diperbaiki ────────────────
from checker.core.rca import (
    Category,
    ErrorCode,
    RCAEngine,
    RCAResult,
    RCARule,
    Severity,
    _get_error_line,
    get_code_context,
)

__version__ = "1.0.0"
__all__ = ["register_all", "self_test_project"]

_logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
#  BAGIAN 1 — DOMAIN EXCEPTION RULES
# ═══════════════════════════════════════════════════════════════════════════════

class AxiomViolationRule(RCARule):
    """
    Deteksi pelanggaran Aksioma Akuntansi inti dari axioms/.
    Files nyata: axioms/axiom_violation.py, axioms/double_entry.py, ...
    """
    _AXIOM_PATTERNS: list[tuple[re.Pattern, str, str, Severity]] = [
        (
            re.compile(
                r"(double.?entry|debit.*credit.*unbalanced|credit.*debit.*unbalanced|"
                r"total.debit.*!=.*total.credit|jurnal.tidak.seimbang|unbalanced.journal)",
                re.I,
            ),
            "Pelanggaran aksioma Double-Entry: total debit ≠ total kredit.",
            "Validasi setiap JournalEntry: sum(debit_lines) == sum(credit_lines) "
            "sebelum persist. Periksa axioms/double_entry.py untuk constraint.",
            Severity.FATAL,
        ),
        (
            re.compile(
                r"(immutab|posted.journal.*modif|journal.*sudah.diposting|"
                r"cannot.modif.*posted|ImmutabilityViolation|tamper)",
                re.I,
            ),
            "Pelanggaran aksioma Immutability: journal yang sudah diposting tidak boleh diubah.",
            "Gunakan reversal journal (reverse_journal use-case) bukan edit langsung. "
            "Lihat axioms/immutability.py dan application/use_cases/reverse_journal.py.",
            Severity.FATAL,
        ),
        (
            re.compile(
                r"(accrual.basis|cash.basis.*not.allowed|AccrualBasisViolation|"
                r"transaksi.*belum.jatuh.tempo.*diakui|revenue.recognition.violation)",
                re.I,
            ),
            "Pelanggaran aksioma Accrual Basis: pengakuan pendapatan/biaya tidak sesuai periode.",
            "Periksa axioms/accrual_basis.py. Gunakan fiscal period yang benar. "
            "Revenue hanya diakui saat sudah earned (IFRS 15 / PSAK 72).",
            Severity.CRITICAL,
        ),
        (
            re.compile(
                r"(conservation.of.value|nilai.tidak.konsisten|ConservationOfValueError|"
                r"entity.isolation.*violated|cross.entity.contamination)",
                re.I,
            ),
            "Pelanggaran aksioma Conservation of Value atau Entity Isolation.",
            "Pastikan transaksi antar entitas (intercompany) menggunakan "
            "elimination entries. Lihat axioms/entity_isolation.py dan "
            "application/use_cases/intercompany_elimination.py.",
            Severity.CRITICAL,
        ),
        (
            re.compile(
                r"(AxiomViolation|axiom.*violation|pelanggaran.aksioma)",
                re.I,
            ),
            "Pelanggaran aksioma akuntansi terdeteksi.",
            "Periksa axioms/ untuk daftar lengkap aksioma. "
            "Trace exception ke axiom spesifik yang dilanggar.",
            Severity.FATAL,
        ),
    ]

    def __init__(self) -> None:
        super().__init__(priority=200, category=Category.DDD, name="AxiomViolationRule")

    def match(self, exc, frames, context) -> bool:
        cls_name = type(exc).__name__
        if any(k in cls_name for k in (
            "AxiomViolation", "DoubleEntry", "Immutability",
            "AccrualBasis", "ConservationOfValue", "EntityIsolation",
        )):
            return True
        msg = str(exc).lower()
        return any(p.search(msg) for p, *_ in self._AXIOM_PATTERNS)

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg = str(exc)
        for pattern, root_cause, fix, sev in self._AXIOM_PATTERNS:
            if pattern.search(msg):
                evidence = [f"Exception: {type(exc).__name__}: {msg[:300]}"]
                if frames:
                    frame = frames[-1]
                    code  = get_code_context(frame.filename, frame.lineno)
                    line  = _get_error_line(code, frame.lineno)
                    if line:
                        evidence.append(f"Lokasi: {frame.filename}:{frame.lineno} → {line}")
                    axiom_frames = [f for f in frames if "axiom" in f.filename.lower()]
                    if axiom_frames:
                        evidence.append(
                            f"Axiom file: {axiom_frames[-1].filename}:{axiom_frames[-1].lineno}"
                        )
                return RCAResult(
                    severity=sev, category=Category.DDD,
                    error_code=ErrorCode.ERP_VALIDATION,
                    root_cause=root_cause, evidence=evidence,
                    impact=[
                        "Integritas data akuntansi KRITIS terancam.",
                        "Laporan keuangan tidak dapat dipercaya jika ini lolos.",
                        "Auditor eksternal akan menolak laporan dengan temuan ini.",
                    ],
                    suggested_fix=fix, raw_error=msg, confidence=0.95,
                )
        return None


class ConstitutionViolationRule(RCARule):
    """Deteksi pelanggaran Constitutional Invariants dari constitution/."""
    _CONST_PATTERN = re.compile(
        r"(ConstitutionViolation|ForbiddenState|InvariantBroken|"
        r"SovereigntyViolation|constitutional.*invariant|"
        r"forbidden.state.detected|supreme.law.violated|"
        r"enforcement.engine.*reject)",
        re.I,
    )

    def __init__(self) -> None:
        super().__init__(priority=195, category=Category.DDD, name="ConstitutionViolationRule")

    def match(self, exc, frames, context) -> bool:
        return bool(self._CONST_PATTERN.search(str(exc))) or \
               any("constitution" in f.filename.lower() for f in frames)

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg    = str(exc)
        cframes= [f for f in frames if "constitution" in f.filename.lower()]
        evidence = [f"Constitutional violation: {type(exc).__name__}: {msg[:300]}"]
        if cframes:
            evidence.append(f"Constitution module: {cframes[-1].filename}:{cframes[-1].lineno}")
        return RCAResult(
            severity=Severity.FATAL, category=Category.DDD,
            error_code=ErrorCode.ERP_VALIDATION,
            root_cause=(
                "Pelanggaran Constitutional Invariant — kondisi yang dilarang secara absolut "
                "oleh constitution/forbidden_states.py terdeteksi. "
                "Sistem masuk ke state yang tidak valid."
            ),
            evidence=evidence,
            impact=[
                "Sistem ERP dalam kondisi tidak valid (forbidden state).",
                "Semua operasi berikutnya akan menghasilkan data tidak konsisten.",
                "Diperlukan rollback dan forensic audit segera.",
            ],
            suggested_fix=(
                "1. Hentikan operasi segera — jangan lanjutkan transaksi. "
                "2. Jalankan application/use_cases/disaster_recovery_replay.py untuk forensik. "
                "3. Periksa constitution/forbidden_states.py untuk state yang dilanggar. "
                "4. Gunakan constitution/amendment_protocol.py jika aturan perlu diubah (prosedur formal)."
            ),
            raw_error=msg, confidence=0.97,
        )


class KernelGuardViolationRule(RCARule):
    """Deteksi pelanggaran Kernel Guards dari kernel/guards/."""
    _GUARD_PATTERNS: list[tuple[re.Pattern, str, str, str, Severity]] = [
        (
            re.compile(r"(PeriodLock|period.*locked|period.*closed|tutup.buku|"
                       r"fiscal.*period.*lock|posting.*closed.*period)", re.I),
            "PeriodLockViolation",
            "Periode fiskal sudah dikunci — tidak ada posting yang diizinkan.",
            "Minta approval dari Finance Manager untuk reopen period "
            "(application/use_cases/period_reopen_with_audit.py). "
            "Audit trail akan dicatat di audit/event_writer_immutable.py.",
            Severity.CRITICAL,
        ),
        (
            re.compile(r"(SodViolation|segregation.of.duties|sod.*enforc|"
                       r"user.*tidak.bisa.*approve.*sendiri|four.eyes|"
                       r"same.user.*creator.*approver)", re.I),
            "SodViolation (Segregation of Duties)",
            "Pelanggaran Segregation of Duties — user yang sama tidak boleh "
            "membuat dan menyetujui transaksi.",
            "Gunakan four-eyes approval workflow: "
            "application/use_cases/approve_journal_four_eyes.py. "
            "Periksa kernel/guards/sod_enforcer.py untuk aturan SOD.",
            Severity.FATAL,
        ),
        (
            re.compile(r"(BudgetExhausted|BudgetNotApproved|budget.*exceeded|"
                       r"melebihi.anggaran|over.budget|budget.*not.*available|"
                       r"BudgetAvailability)", re.I),
            "BudgetExhausted / BudgetNotApproved",
            "Transaksi melebihi anggaran yang tersedia atau anggaran belum disetujui.",
            "Periksa saldo anggaran di domain/budget/. "
            "Ajukan budget revision atau minta authorization dari budget owner. "
            "Lihat kernel/guards/budget_availability.py.",
            Severity.HIGH,
        ),
        (
            re.compile(r"(CreditLimitExceeded|credit.limit|batas.kredit|"
                       r"piutang.*melebihi.limit|over.credit.limit)", re.I),
            "CreditLimitExceeded",
            "Transaksi AR/penjualan melebihi credit limit pelanggan.",
            "Periksa domain/subledger_ar/ untuk credit limit pelanggan. "
            "Minta approval dari Credit Manager atau ubah credit limit di master data.",
            Severity.HIGH,
        ),
        (
            re.compile(r"(UnauthorizedOperation|not.authorized|tidak.berwenang|"
                       r"authority.matrix|tidak.memiliki.hak|permission.denied.*erp|"
                       r"AuthorityMatrix)", re.I),
            "UnauthorizedOperation",
            "Operasi tidak diizinkan — user tidak ada di authority matrix.",
            "Periksa kernel/guards/authority_matrix.py untuk permission yang diperlukan. "
            "Hubungi IAM administrator untuk grant permission: domain/iam/.",
            Severity.CRITICAL,
        ),
        (
            re.compile(r"(SystemFrozen|EmergencyFreeze|sistem.*dibekukan|"
                       r"emergency.freeze|system.frozen)", re.I),
            "SystemFrozenError (Emergency Freeze)",
            "Sistem ERP dalam kondisi Emergency Freeze — semua operasi diblokir.",
            "Hanya Super Admin yang bisa unfreeze: kernel/guards/emergency_freeze.py. "
            "Cari tahu penyebab freeze di audit/tamper_alert_trigger.py. "
            "Jangan bypass — ini keamanan darurat.",
            Severity.FATAL,
        ),
        (
            re.compile(r"(LegalEntityBoundary|batas.entitas.hukum|"
                       r"cross.entity.*not.allowed|intercompany.*not.configured|"
                       r"legal.entity.*mismatch)", re.I),
            "LegalEntityBoundaryViolation",
            "Transaksi melintasi batas entitas hukum yang tidak dikonfigurasi.",
            "Konfigurasikan intercompany relationship di domain/legal_entity/. "
            "Gunakan application/use_cases/intercompany_elimination.py untuk "
            "eliminasi transaksi lintas entitas yang valid.",
            Severity.CRITICAL,
        ),
        (
            re.compile(r"(AMLFlag|AMLFlagged|anti.money.laundering|suspicious.*transaction|"
                       r"transaksi.*mencurigakan|aml.*risk.score)", re.I),
            "AMLFlaggedTransaction",
            "Transaksi ditandai sebagai mencurigakan oleh sistem AML.",
            "Transaksi diblokir oleh kernel/guards/async_guards/anti_money_laundering.py. "
            "Review di compliance/aml_risk_scorer.py dan laporkan sesuai prosedur PPATK "
            "jika diperlukan. Jangan release tanpa persetujuan Compliance Officer.",
            Severity.FATAL,
        ),
        (
            re.compile(r"(FraudPattern|fraud.*detected|pola.*kecurangan|"
                       r"FraudPatternDetected|anomali.*transaksi)", re.I),
            "FraudPatternDetected",
            "Pola kecurangan terdeteksi oleh fraud detection engine.",
            "Transaksi diblokir oleh kernel/guards/async_guards/fraud_pattern_detector.py. "
            "Eskalasi ke Internal Audit segera. "
            "Jalankan audit/forensic_replayer.py untuk investigasi trail.",
            Severity.FATAL,
        ),
        (
            re.compile(r"(CurrencyMismatch|mata.uang.*tidak.cocok|currency.*mismatch|"
                       r"CurrencyValidat|forex.*rate.*missing)", re.I),
            "CurrencyMismatchError",
            "Mismatch mata uang — kurs tidak tersedia atau kode currency salah.",
            "Periksa domain/forex/ untuk kurs yang diperlukan. "
            "Jalankan application/use_cases/forex_revaluation.py jika kurs expired. "
            "Lihat kernel/guards/currency_validator.py.",
            Severity.HIGH,
        ),
        (
            re.compile(r"(TemporalConsistency|temporal.*violation|"
                       r"tanggal.*transaksi.*sebelum.*posting|backdate.*not.allowed)", re.I),
            "TemporalConsistencyError",
            "Pelanggaran konsistensi temporal — tanggal transaksi tidak valid.",
            "Periksa kernel/guards/temporal_consistency.py. "
            "Backdate hanya diizinkan dengan approval khusus di dalam periode yang terbuka.",
            Severity.HIGH,
        ),
        (
            re.compile(r"(RegulatoryViolation|regulat.*violat|kepatuhan.*gagal|"
                       r"compliance.*failed|OJK|PPATK|DJP.*rejected)", re.I),
            "RegulatoryViolation",
            "Pelanggaran aturan regulasi (OJK/PPATK/DJP) terdeteksi.",
            "Periksa compliance/ dan policy_engine/ untuk aturan yang dilanggar. "
            "Hubungi Compliance Officer sebelum melanjutkan.",
            Severity.FATAL,
        ),
    ]

    def __init__(self) -> None:
        super().__init__(priority=190, category=Category.DDD, name="KernelGuardViolationRule")

    def match(self, exc, frames, context) -> bool:
        cls_name = type(exc).__name__
        guard_class_patterns = (
            "PeriodLock", "SodViolation", "Budget", "CreditLimit",
            "Unauthorized", "SystemFrozen", "LegalEntity", "AML", "Fraud",
            "CurrencyMismatch", "Temporal", "Regulatory", "GuardException",
        )
        if any(k in cls_name for k in guard_class_patterns):
            return True
        if any("kernel/guards" in f.filename.replace("\\", "/").lower() or
               "kernel\\guards" in f.filename.lower()
               for f in frames):
            return True
        msg = str(exc)
        return any(p.search(msg) for p, *_ in self._GUARD_PATTERNS)

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg = str(exc)
        for pattern, exc_type, root_cause, fix, sev in self._GUARD_PATTERNS:
            if pattern.search(msg) or exc_type.lower().replace(" ", "") in type(exc).__name__.lower():
                evidence = [
                    f"Guard violation: {type(exc).__name__}",
                    f"Message: {msg[:300]}",
                ]
                guard_frames = [
                    f for f in frames
                    if "guard" in f.filename.replace("\\", "/").lower()
                ]
                if guard_frames:
                    gf = guard_frames[-1]
                    evidence.append(f"Guard file: {gf.filename}:{gf.lineno} in {gf.name}")
                if frames:
                    caller = frames[0]
                    evidence.append(
                        f"Dipanggil dari: {caller.filename}:{caller.lineno} in {caller.name}"
                    )
                return RCAResult(
                    severity=sev, category=Category.DDD,
                    error_code=ErrorCode.PERMISSION_DENIED
                    if "Unauthorized" in exc_type else ErrorCode.ERP_VALIDATION,
                    root_cause=root_cause, evidence=evidence,
                    impact=self._impact_for(exc_type),
                    suggested_fix=fix, raw_error=msg, confidence=0.93,
                )
        if any("kernel/guard" in f.filename.replace("\\","/").lower() for f in frames):
            return RCAResult(
                severity=Severity.CRITICAL, category=Category.DDD,
                error_code=ErrorCode.ERP_VALIDATION,
                root_cause=f"Kernel guard menolak operasi: {type(exc).__name__}",
                evidence=[f"Guard error: {msg[:300]}"],
                impact=["Operasi ditolak oleh sistem keamanan ERP."],
                suggested_fix="Periksa kernel/guards/ untuk guard yang aktif dan aturannya.",
                raw_error=msg, confidence=0.8,
            )
        return None

    @staticmethod
    def _impact_for(exc_type: str) -> list[str]:
        _impacts: dict[str, list[str]] = {
            "SodViolation": [
                "Pelanggaran SOD adalah temuan audit KRITIKAL (SOX control failure).",
                "Jika lolos, menciptakan risiko fraud dan salah saji material.",
                "Auditor Big 4 akan menerbitkan qualified opinion.",
            ],
            "AMLFlagged": [
                "Transaksi mencurigakan harus dilaporkan ke PPATK dalam 3 hari kerja.",
                "Kegagalan lapor = sanksi pidana bagi direksi.",
            ],
            "FraudPattern": [
                "Potensi kerugian finansial langsung.",
                "Reputasi perusahaan berisiko jika tidak segera ditangani.",
            ],
        }
        for key, impacts in _impacts.items():
            if key.lower() in exc_type.lower():
                return impacts
        return [
            "Operasi ditolak oleh kernel guard — tidak ada data yang dimodifikasi.",
            "Perlu tindakan korektif sebelum transaksi bisa dilanjutkan.",
        ]


# ═══════════════════════════════════════════════════════════════════════════════
#  BAGIAN 2 — INFRASTRUCTURE EXCEPTION RULES (project-specific)
# ═══════════════════════════════════════════════════════════════════════════════

class InfrastructureDatabaseRule(RCARule):
    """Deteksi exception dari infrastructure/database/ dan persistence_orm/."""
    _DB_PATTERNS = re.compile(
        r"(DatabaseException|ConnectionPoolExhausted|DatabaseTimeout|"
        r"DeadlockDetected|ForeignKeyViolation|UniqueConstraintViolation|"
        r"CheckConstraintViolation|NullConstraintViolation|"
        r"SchemaVersionMismatch|MigrationPending|"
        r"sqlalchemy.*error|psycopg2.*error|asyncpg.*error|"
        r"could not serialize access|deadlock detected|"
        r"duplicate key.*violates unique|"
        r"null value.*violates not-null|"
        r"foreign key.*violates|migration.*pending|"
        r"relation.*does not exist|column.*does not exist|"
        r"too many connections|remaining connection slots|"
        r"SSL connection.*been closed|server unexpectedly closed)",
        re.I,
    )

    _TABLE_TO_DOMAIN: dict[str, str] = {
        "journal": "domain/journal — Periksa JournalEntry aggregate",
        "account": "domain/coa — Periksa CoA aggregate",
        "ap_invoice": "domain/subledger_ap — Periksa AP Invoice aggregate",
        "ar_invoice": "domain/subledger_ar — Periksa AR Invoice aggregate",
        "payroll": "domain/payroll — Periksa Payroll aggregate",
        "fiscal_period": "domain/fiscal_period — Periksa FiscalPeriod",
        "fixed_asset": "domain/fixed_asset — Periksa FixedAsset aggregate",
        "inventory": "domain/inventory — Periksa Inventory aggregate",
        "budget": "domain/budget — Periksa Budget aggregate",
        "purchase_order": "domain/purchase_sales — Periksa PO aggregate",
        "sales_order": "domain/purchase_sales — Periksa SO aggregate",
        "tax": "domain/tax_transaction — Periksa TaxTransaction",
        "forex": "domain/forex — Periksa ForexRate",
        "audit_event": "audit/ — Audit event store bermasalah",
        "employee": "domain/customer_supplier_employee",
        "bank_cash": "domain/bank_cash — Periksa BankAccount aggregate",
        "manufacturing": "domain/manufacturing — Periksa Manufacturing aggregate",
    }

    def __init__(self) -> None:
        super().__init__(priority=185, category=Category.DATABASE, name="InfrastructureDatabaseRule")

    def match(self, exc, frames, context) -> bool:
        if self._DB_PATTERNS.search(str(exc)):
            return True
        cls_name = type(exc).__name__
        return any(k in cls_name for k in (
            "DatabaseException", "ConnectionPool", "Deadlock",
            "UniqueConstraint", "ForeignKey", "CheckConstraint",
            "Migration", "SchemaVersion", "SQLAlchemy",
        ))

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg      = str(exc)
        evidence : list[str] = [f"DB Exception: {type(exc).__name__}: {msg[:300]}"]
        impact   : list[str] = []
        root_cause= suggested_fix = ""
        confidence= 0.85
        severity  = Severity.FATAL

        domain_hint = ""
        for f in frames:
            fname = f.filename.replace("\\", "/").lower()
            if "persistence_orm" in fname:
                for table_key, domain_desc in self._TABLE_TO_DOMAIN.items():
                    if table_key in fname:
                        domain_hint = domain_desc
                        evidence.append(f"ORM table file: {f.filename}")
                        break

        if re.search(r"deadlock", msg, re.I):
            root_cause    = "Deadlock terdeteksi di PostgreSQL — dua transaksi saling menunggu."
            suggested_fix = (
                "1. Pastikan urutan lock konsisten di seluruh aplikasi. "
                "2. Kurangi durasi transaksi — commit lebih awal. "
                "3. Periksa infrastructure/database/postgres_connection_pool_manager.py "
                "   untuk tuning pool timeout. "
                "4. Di production: aktifkan lock_timeout di PostgreSQL config."
            )
            impact.append("Semua transaksi yang terlibat di-rollback otomatis.")
            confidence = 0.92

        elif re.search(r"duplicate key|unique.*constraint|violates unique", msg, re.I):
            root_cause    = "Duplicate key violation — data yang sudah ada dicoba di-insert ulang."
            suggested_fix = (
                "1. Gunakan upsert pattern (INSERT ... ON CONFLICT DO UPDATE). "
                "2. Periksa apakah proses idempotency berjalan. "
                "3. Cek outbox pattern: application/outbox/outbox_relay_service.py "
                "   mungkin memproses event dua kali (at-least-once delivery)."
            )
            severity   = Severity.HIGH
            confidence = 0.9

        elif re.search(r"foreign key.*violates|violates.*foreign key", msg, re.I):
            root_cause    = "Foreign key violation — referenced record tidak ada."
            suggested_fix = (
                "1. Pastikan parent record dibuat sebelum child record. "
                "2. Periksa urutan insert di UnitOfWork (adapters/secondary_impl/sqlalchemy_unit_of_work_impl.py). "
                "3. Jika menggunakan Saga pattern, periksa saga state di application/sagas/."
            )
            severity   = Severity.CRITICAL
            confidence = 0.9

        elif re.search(r"too many connections|remaining connection slots", msg, re.I):
            root_cause    = "PostgreSQL connection pool habis — max_connections terlampaui."
            suggested_fix = (
                "1. Kurangi pool_size di config environment atau naikkan max_connections PostgreSQL. "
                "2. Pastikan semua session di-close setelah dipakai (gunakan UoW context manager). "
                "3. Aktifkan PgBouncer atau connection pooling di "
                "   infrastructure/database/postgres_connection_pool_manager.py. "
                "4. Periksa zombie connections dengan: SELECT count(*) FROM pg_stat_activity;"
            )
            impact.append("Semua request API baru akan gagal sampai connections freed.")
            confidence = 0.93

        elif re.search(r"migration.*pending|relation.*does not exist|column.*does not exist", msg, re.I):
            root_cause    = "Skema database tidak sinkron — migration belum dijalankan."
            suggested_fix = (
                "Jalankan: alembic upgrade head (dari folder migrations/). "
                "Periksa versi migration terbaru di migrations/. "
                "Pastikan deployment menjalankan migration sebelum start aplikasi."
            )
            severity   = Severity.FATAL
            confidence = 0.95

        else:
            root_cause    = f"Database error: {type(exc).__name__}: {msg[:200]}"
            suggested_fix = (
                "Periksa infrastructure/database/database_exceptions.py untuk error taxonomy. "
                "Cek PostgreSQL logs untuk detail error. "
                "Lihat infrastructure/telemetry/ untuk monitoring metrics."
            )

        if domain_hint:
            impact.append(f"Domain terdampak: {domain_hint}")
        impact.append("Operasi database gagal — data mungkin tidak tersimpan.")

        return RCAResult(
            severity=severity, category=Category.DATABASE,
            error_code=ErrorCode.DB_CONNECTION_FAIL,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=msg, confidence=confidence,
        )


class MessageBrokerRule(RCARule):
    """Deteksi exception dari infrastructure/message_broker/ dan event_gateway/."""
    _BROKER_PATTERN = re.compile(
        r"(BrokerException|BrokerUnavailable|MessagePublishFailed|"
        r"ConsumerGroupError|DeadLetterQueueFull|DeadLetterQueue|"
        r"dead.letter|EventGatewayError|"
        r"KafkaProducerError|KafkaConsumerError|OutboxRelay|"
        r"event.*publish.*failed|domain.*event.*not.*sent|"
        r"outbox.*stuck|"
        r"message.*broker.*connection|topic.*not.*found|"
        r"consumer.*group.*rebalancing)",
        re.I,
    )

    def __init__(self) -> None:
        super().__init__(priority=180, category=Category.INFRASTRUCTURE, name="MessageBrokerRule")

    def match(self, exc, frames, context) -> bool:
        if self._BROKER_PATTERN.search(str(exc)):
            return True
        return any(
            any(k in f.filename.replace("\\", "/").lower()
                for k in ("kafka", "message_broker", "event_gateway", "outbox"))
            for f in frames
        )

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg     = str(exc)
        evidence= [f"Broker/Event error: {type(exc).__name__}: {msg[:300]}"]

        broker_frames = [
            f for f in frames
            if any(k in f.filename.replace("\\","/").lower()
                   for k in ("kafka", "message_broker", "event_gateway", "outbox"))
        ]
        if broker_frames:
            bf = broker_frames[-1]
            evidence.append(f"Broker file: {bf.filename}:{bf.lineno} in {bf.name}")

        if re.search(r"dead.letter|DeadLetter", msg, re.I):
            return RCAResult(
                severity=Severity.CRITICAL, category=Category.INFRASTRUCTURE,
                error_code=ErrorCode.KAFKA_FAIL,
                root_cause="Event masuk ke Dead Letter Queue — konsumer gagal memproses berulang kali.",
                evidence=evidence,
                impact=[
                    "Domain event tidak diproses — read model / projections tidak terupdate.",
                    "Eventual consistency rusak — UI bisa menampilkan data lama.",
                    "Jika outbox, transaksi DB sudah commit tapi event belum terkirim.",
                ],
                suggested_fix=(
                    "1. Periksa adapters/secondary_impl/kafka_dead_letter_handler.py "
                    "   untuk logic retry. "
                    "2. Inspect dead letter topic: kafka-console-consumer --topic dlq.*. "
                    "3. Fix konsumer error lalu replay dari DLQ. "
                    "4. Cek application/outbox/outbox_relay_service.py untuk stuck outbox."
                ),
                raw_error=msg, confidence=0.88,
            )

        if re.search(r"outbox.*stuck|OutboxRelay", msg, re.I):
            return RCAResult(
                severity=Severity.HIGH, category=Category.INFRASTRUCTURE,
                error_code=ErrorCode.KAFKA_FAIL,
                root_cause="Outbox relay stuck — event di tabel outbox tidak terkirim ke Kafka.",
                evidence=evidence,
                impact=[
                    "Domain events tertunda — subscriber tidak mendapat update.",
                    "Eventual consistency degraded.",
                ],
                suggested_fix=(
                    "1. Periksa application/outbox/outbox_poller.py — apakah poller berjalan. "
                    "2. Cek status tabel outbox di database. "
                    "3. Restart outbox relay service jika stuck."
                ),
                raw_error=msg, confidence=0.85,
            )

        return RCAResult(
            severity=Severity.FATAL, category=Category.INFRASTRUCTURE,
            error_code=ErrorCode.KAFKA_FAIL,
            root_cause=(
                "Message broker (Kafka) tidak tersedia atau error "
                f"— {type(exc).__name__}"
            ),
            evidence=evidence,
            impact=[
                "Domain events tidak terkirim — eventual consistency broken.",
                "Jika menggunakan Saga pattern, saga state mungkin terhenti.",
            ],
            suggested_fix=(
                "1. Periksa status Kafka broker. "
                "2. Cek adapters/secondary_impl/kafka_producer_wrapper.py "
                "   untuk retry/backoff configuration. "
                "3. Gunakan Outbox pattern (application/outbox/) sebagai fallback. "
                "4. Monitor di infrastructure/telemetry/."
            ),
            raw_error=msg, confidence=0.87,
        )


class CachingRule(RCARule):
    """Deteksi exception dari infrastructure/caching/ dan Redis."""
    _CACHE_PATTERN = re.compile(
        r"(CachingException|CacheConnectionFailed|CacheSerializationError|"
        r"CacheKeyNotFound|RedisConnectionError|redis.*timeout|"
        r"cache.*miss.*critical|CacheInvalidationFailed|"
        r"lock.*acquisition.*failed|DistributedLockTimeout)",
        re.I,
    )

    def __init__(self) -> None:
        super().__init__(priority=170, category=Category.INFRASTRUCTURE, name="CachingRule")

    def match(self, exc, frames, context) -> bool:
        return self._CACHE_PATTERN.search(str(exc)) is not None or \
               any(k in type(exc).__name__ for k in ("Cache", "Redis", "Lock"))

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg = str(exc)
        if re.search(r"DistributedLock|lock.*acquisition", msg, re.I):
            return RCAResult(
                severity=Severity.HIGH, category=Category.INFRASTRUCTURE,
                error_code=ErrorCode.REDIS_FAIL,
                root_cause="Distributed lock tidak bisa diperoleh — mungkin ada proses lain yang memegang lock atau Redis down.",
                evidence=[f"Lock error: {msg[:200]}"],
                impact=["Operasi concurrent tidak bisa dieksekusi — terjadi bottleneck."],
                suggested_fix=(
                    "1. Periksa kernel/distributed_lock_redis.py untuk timeout config. "
                    "2. Pastikan Redis tersedia. "
                    "3. Periksa apakah ada lock yang tidak di-release (zombie lock)."
                ),
                raw_error=msg, confidence=0.88,
            )
        return RCAResult(
            severity=Severity.HIGH, category=Category.INFRASTRUCTURE,
            error_code=ErrorCode.REDIS_FAIL,
            root_cause=f"Cache layer error: {type(exc).__name__}: {msg[:200]}",
            evidence=[f"{type(exc).__name__}: {msg[:300]}"],
            impact=["Performa ERP degraded — setiap request harus ke database."],
            suggested_fix=(
                "1. Periksa status Redis server. "
                "2. Lihat infrastructure/caching/caching_exceptions.py. "
                "3. Aplikasi harus bisa fallback ke database jika cache down — "
                "   pastikan adapters/secondary_impl/redis_cache_adapter_impl.py "
                "   implementasikan graceful fallback."
            ),
            raw_error=msg, confidence=0.82,
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  BAGIAN 3 — APPLICATION LAYER RULES (project-specific)
# ═══════════════════════════════════════════════════════════════════════════════

class SagaOrchestrationRule(RCARule):
    """Deteksi error di application/sagas/."""
    _SAGA_PATTERN = re.compile(
        r"(SagaException|SagaCompensationFailed|SagaStepFailed|SagaTimeout|"
        r"SagaRollbackFailed|saga.*stuck|saga.*orphaned|"
        r"compensation.*failed|saga.*state.*invalid|"
        r"procurement.*saga|sales.*saga|payroll.*saga|"
        r"coretax.*saga|manufacturing.*saga)",
        re.I,
    )

    _SAGA_TYPES: dict[str, str] = {
        "procurement": "Procurement Saga (PO → GR → AP Invoice → Payment)",
        "sales"      : "Sales Saga (SO → Delivery → AR Invoice → Collection)",
        "payroll"    : "Payroll Saga (Payroll Run → Journal → Bank Transfer)",
        "coretax"    : "Coretax Submission Saga (Tax Filing → DJP Submission → Confirmation)",
        "manufacturing": "Manufacturing Saga (Work Order → BOM → Production → COGS)",
    }

    def __init__(self) -> None:
        super().__init__(priority=175, category=Category.DDD, name="SagaOrchestrationRule")

    def match(self, exc, frames, context) -> bool:
        if self._SAGA_PATTERN.search(str(exc)):
            return True
        if any(k in type(exc).__name__ for k in ("Saga", "Compensation")):
            return True
        return any("sagas" in f.filename.replace("\\", "/").lower() for f in frames)

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg         = str(exc)
        saga_frames = [f for f in frames if "sagas" in f.filename.replace("\\","/").lower()]
        evidence    = [f"Saga error: {type(exc).__name__}: {msg[:300]}"]

        saga_type = "Unknown Saga"
        for key, desc in self._SAGA_TYPES.items():
            if key in msg.lower() or any(key in f.filename.lower() for f in saga_frames):
                saga_type = desc
                break

        if saga_frames:
            sf = saga_frames[-1]
            evidence.append(f"Saga file: {sf.filename}:{sf.lineno} in {sf.name}")

        is_compensation = bool(re.search(r"compensation.*failed|compensat", msg, re.I))

        return RCAResult(
            severity=Severity.FATAL if is_compensation else Severity.CRITICAL,
            category=Category.DDD,
            error_code=ErrorCode.TRANSACTION_INTEGRITY,
            root_cause=(
                f"{'Kompensasi' if is_compensation else 'Eksekusi'} Saga gagal: {saga_type}. "
                f"Exception: {type(exc).__name__}: {msg[:150]}"
            ),
            evidence=evidence,
            impact=[
                f"Saga tidak selesai — state bisnis {saga_type} tidak konsisten.",
                "Data mungkin setengah-setengah: sebagian step sudah commit, sebagian belum.",
                "Kompensasi (rollback bisnis) diperlukan untuk semua step yang sudah sukses."
                if not is_compensation else
                "KRITIS: Kompensasi gagal — sistem dalam inconsistent state yang tidak bisa auto-recover.",
            ],
            suggested_fix=(
                "1. Periksa saga state di application/sagas/saga_state_store.py. "
                "2. Identifikasi step terakhir yang berhasil dari saga state. "
                "3. Jalankan manual compensation jika auto-compensation gagal. "
                "4. Lihat application/sagas/saga_orchestrator_base.py "
                "   untuk rollback mechanism. "
                "5. Monitor saga state di adapters/secondary_impl/saga_state_store_adapter.py."
                if not is_compensation else
                "KRITIS: "
                "1. Eskalasi ke Tim Teknis Senior segera. "
                "2. Jangan ada operasi baru sampai state di-resolve. "
                "3. Jalankan application/use_cases/disaster_recovery_replay.py. "
                "4. Manual data reconciliation mungkin diperlukan."
            ),
            raw_error=msg, confidence=0.91,
        )


class BootstrapDIRule(RCARule):
    """Deteksi error di bootstrap/ dan dependency injection container."""
    _DI_PATTERN = re.compile(
        r"(DIException|CircularDependency.*DI|ServiceNotRegistered|"
        r"PortNotBound|AdapterNotFound|BootstrapException|"
        r"DependencyResolutionFailed|ScopedContextError|"
        r"lifecycle.*hook.*failed|ioc.*container|"
        r"port.*not.*registered|adapter.*not.*found|"
        r"cannot.*resolve.*service|dependency.*cycle.*detected)",
        re.I,
    )

    def __init__(self) -> None:
        super().__init__(priority=180, category=Category.DI, name="BootstrapDIRule")

    def match(self, exc, frames, context) -> bool:
        if self._DI_PATTERN.search(str(exc)):
            return True
        if any(k in type(exc).__name__ for k in (
            "DI", "Bootstrap", "Container", "ServiceNot", "PortNot", "Adapter"
        )):
            return True
        return any(
            any(k in f.filename.replace("\\","/").lower()
                for k in ("bootstrap", "dependency_container", "ioc_container"))
            for f in frames
        )

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg = str(exc)
        evidence = [f"DI/Bootstrap error: {type(exc).__name__}: {msg[:300]}"]
        di_frames = [
            f for f in frames
            if any(k in f.filename.replace("\\","/").lower()
                   for k in ("bootstrap", "dependency_container", "ioc"))
        ]
        if di_frames:
            evidence.append(f"DI file: {di_frames[-1].filename}:{di_frames[-1].lineno}")

        is_circular = bool(re.search(r"circular.depend|cycle.*detected", msg, re.I))

        return RCAResult(
            severity=Severity.FATAL, category=Category.DI,
            error_code=ErrorCode.CONTAINER_RESOLVE_FAIL,
            root_cause=(
                "Circular dependency terdeteksi di DI Container — "
                "dua service saling bergantung."
                if is_circular else
                f"Service/Port tidak terdaftar di IoC Container: {msg[:200]}"
            ),
            evidence=evidence,
            impact=[
                "Aplikasi tidak bisa start — bootstrap gagal.",
                "Semua endpoint API tidak tersedia.",
            ],
            suggested_fix=(
                "1. Jalankan bootstrap/dependency_container/dependency_graph_validator.py "
                "   untuk visualisasi dependency graph. "
                "2. Pecah circular dependency dengan interface/port abstraction. "
                "3. Gunakan lazy injection atau factory pattern."
                if is_circular else
                "1. Daftarkan service di bootstrap/dependency_container/service_registry.py. "
                "2. Pastikan adapter ter-register di bootstrap/dependency_container/adapter_registry.py. "
                "3. Jalankan bootstrap/dependency_container/auto_register_ports.py "
                "   untuk auto-registration. "
                "4. Periksa bootstrap/health_probe.py untuk dependency health check."
            ),
            raw_error=msg, confidence=0.92,
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  BAGIAN 4 — COMPLIANCE & POLICY RULES (project-specific)
# ═══════════════════════════════════════════════════════════════════════════════

class PolicyEngineRule(RCARule):
    """Deteksi error dari policy_engine/ — IFRS, PSAK, Tax Indonesia."""
    _POLICY_PATTERNS: list[tuple[re.Pattern, str, str]] = [
        (
            re.compile(r"(IFRS9|IFRS 9|ifrs.*9|financial.*instrument.*classif|"
                       r"ECL.*calculation|expected.credit.loss)", re.I),
            "Pelanggaran IFRS 9 (Financial Instruments) — klasifikasi atau ECL calculation.",
            "Periksa policy_engine/ifrs/ifrs_09_financial_instruments.py. "
            "Pastikan aset keuangan diklasifikasi FVTPL/FVOCI/Amortized Cost dengan benar.",
        ),
        (
            re.compile(r"(IFRS15|IFRS 15|revenue.*recognition|performance.*obligation|"
                       r"contract.*asset.*liability|PSAK72|PSAK 72)", re.I),
            "Pelanggaran IFRS 15 / PSAK 72 (Revenue Recognition).",
            "Periksa policy_engine/ifrs/ifrs_15_revenue.py. "
            "5-step model: Identify contract → Performance obligations → "
            "Transaction price → Allocate → Recognize.",
        ),
        (
            re.compile(r"(IFRS16|IFRS 16|lease.*liability|right.of.use|ROU.*asset|"
                       r"PSAK73|PSAK 73|sewa.*guna)", re.I),
            "Pelanggaran IFRS 16 / PSAK 73 (Leases) — pengakuan ROU asset atau lease liability.",
            "Periksa policy_engine/ifrs/ifrs_16_leases.py. "
            "Pastikan lease classification (finance vs operating) sudah benar.",
        ),
        (
            re.compile(r"(IAS36|IAS 36|impairment.*test|goodwill.*impairment|"
                       r"PSAK48|nilai.pakai|recoverable.amount)", re.I),
            "Pelanggaran IAS 36 / PSAK 48 (Impairment Testing).",
            "Periksa policy_engine/ifrs/ias_36_impairment.py. "
            "Jalankan application/use_cases/impairment_testing_annual.py.",
        ),
        (
            re.compile(r"(IAS21|IAS 21|foreign.exchange|kurs.*revaluasi|"
                       r"forex.*revaluation|monetary.*item.*translat|PSAK10)", re.I),
            "Pelanggaran IAS 21 / PSAK 10 (Foreign Currency Translation).",
            "Periksa policy_engine/ifrs/ias_21_foreign_exchange.py. "
            "Jalankan forex revaluation: application/use_cases/forex_revaluation.py.",
        ),
        (
            re.compile(r"(PSAK25|PSAK 25|perubahan.estimasi|accounting.estimate|"
                       r"error.*prior.period|restatement|koreksi.*periode.lalu)", re.I),
            "Pelanggaran PSAK 25 (Perubahan Estimasi / Koreksi Error).",
            "Periksa policy_engine/psak/psak_25_policies_estimates_errors.py. "
            "Error prior period memerlukan restatement laporan keuangan sebelumnya.",
        ),
        (
            re.compile(r"(tax.*exception|PajakException|PPh.*error|PPN.*error|"
                       r"bupot.*gagal|e.faktur.*error|koretax.*reject|NTPN.*invalid|"
                       r"DJP.*response.*error)", re.I),
            "Error perpajakan Indonesia — PPh, PPN, atau integrasi Coretax DJP.",
            "Periksa policy_engine/tax_indonesia/tax_exceptions.py. "
            "Untuk Coretax: adapters/coretax_djp/coretax_exceptions.py. "
            "Validasi NTPN: adapters/coretax_djp/ntpn_validator.py. "
            "Retry submission: application/sagas/coretax_submission_saga.py.",
        ),
        (
            re.compile(r"(PolicyException|policy.*conflict|policy.*override|"
                       r"jurisdiction.*resolver|PolicyConflict)", re.I),
            "Policy engine conflict — dua policy bertentangan untuk transaksi ini.",
            "Periksa policy_engine/conflict_resolver.py untuk resolution strategy. "
            "Gunakan policy_engine/override_authorizer.py jika override diperlukan (dengan approval).",
        ),
    ]

    def __init__(self) -> None:
        super().__init__(priority=168, category=Category.DDD, name="PolicyEngineRule")

    def match(self, exc, frames, context) -> bool:
        if any(p.search(str(exc)) for p, *_ in self._POLICY_PATTERNS):
            return True
        return any(
            "policy_engine" in f.filename.replace("\\","/").lower() for f in frames
        )

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg = str(exc)
        for pattern, root_cause, fix in self._POLICY_PATTERNS:
            if pattern.search(msg):
                policy_frames = [
                    f for f in frames
                    if "policy_engine" in f.filename.replace("\\","/").lower()
                ]
                evidence = [f"Policy error: {type(exc).__name__}: {msg[:300]}"]
                if policy_frames:
                    pf = policy_frames[-1]
                    evidence.append(f"Policy file: {pf.filename}:{pf.lineno}")
                return RCAResult(
                    severity=Severity.CRITICAL, category=Category.DDD,
                    error_code=ErrorCode.ERP_VALIDATION,
                    root_cause=root_cause, evidence=evidence,
                    impact=[
                        "Laporan keuangan tidak comply dengan standar akuntansi.",
                        "Auditor eksternal akan memberikan qualified/adverse opinion.",
                    ],
                    suggested_fix=fix, raw_error=msg, confidence=0.9,
                )
        return RCAResult(
            severity=Severity.HIGH, category=Category.DDD,
            error_code=ErrorCode.ERP_VALIDATION,
            root_cause=f"Policy engine error: {type(exc).__name__}: {msg[:200]}",
            evidence=[f"{msg[:300]}"],
            impact=["Transaksi tidak comply dengan policy yang berlaku."],
            suggested_fix=(
                "Periksa policy_engine/ untuk policy yang relevan. "
                "Lihat policy_engine/interpreter.py untuk logic evaluasi."
            ),
            raw_error=msg, confidence=0.75,
        )


class ComplianceRule(RCARule):
    """Deteksi error dari compliance/ — SOX, AML, GDPR, OJK LKPUB."""
    _COMPLIANCE_PATTERN = re.compile(
        r"(ComplianceException|SOXControlFailed|AMLRiskExceeded|"
        r"GDPRViolation|SanctionListMatch|OJKValidationFailed|"
        r"sox.*control.*test.*fail|gdpr.*data.*retention|"
        r"sanction.*list.*hit|compliance.*deficiency|"
        r"EthicsViolation|ethics.*exception|"
        r"LegalException|sovereignty.*boundary|"
        r"data.*privacy.*violation)",
        re.I,
    )

    def __init__(self) -> None:
        super().__init__(priority=165, category=Category.SECURITY, name="ComplianceRule")

    def match(self, exc, frames, context) -> bool:
        return self._COMPLIANCE_PATTERN.search(str(exc)) is not None or \
               any(k in type(exc).__name__ for k in (
                   "Compliance", "SOX", "AML", "GDPR", "Sanction", "Ethics", "Legal"
               ))

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg = str(exc)
        if re.search(r"GDPRViolation|data.*privacy|privacy.*violat", msg, re.I):
            return RCAResult(
                severity=Severity.FATAL, category=Category.SECURITY,
                error_code=ErrorCode.PERMISSION_DENIED,
                root_cause="GDPR / Privasi Data Violation — data pribadi diproses tanpa basis hukum.",
                evidence=[f"{type(exc).__name__}: {msg[:300]}"],
                impact=[
                    "Potensi denda GDPR hingga 4% dari global annual turnover.",
                    "Wajib lapor ke otoritas privasi dalam 72 jam (jika terjadi breach).",
                ],
                suggested_fix=(
                    "1. Periksa compliance/gdpr_privacy_checker.py untuk aturan yang dilanggar. "
                    "2. Pastikan data retention policy diikuti. "
                    "3. Hubungi Data Protection Officer (DPO) segera."
                ),
                raw_error=msg, confidence=0.92,
            )
        if re.search(r"SanctionList|sanction.*hit", msg, re.I):
            return RCAResult(
                severity=Severity.FATAL, category=Category.SECURITY,
                error_code=ErrorCode.PERMISSION_DENIED,
                root_cause="Entitas terkena Sanction List — transaksi WAJIB diblokir.",
                evidence=[f"{type(exc).__name__}: {msg[:300]}"],
                impact=[
                    "Melanjutkan transaksi = pelanggaran hukum internasional.",
                    "Eksposur sanksi dari OFAC/UN/EU.",
                ],
                suggested_fix=(
                    "1. Blokir transaksi — JANGAN dilanjutkan tanpa clearance legal. "
                    "2. Periksa compliance/sanction_list_checker.py. "
                    "3. Laporkan ke Compliance Officer dan Legal segera."
                ),
                raw_error=msg, confidence=0.97,
            )
        if re.search(r"SOXControl|sox.*control", msg, re.I):
            return RCAResult(
                severity=Severity.CRITICAL, category=Category.SECURITY,
                error_code=ErrorCode.ERP_VALIDATION,
                root_cause="SOX Control Test Gagal — internal control yang dipersyaratkan tidak terpenuhi.",
                evidence=[f"{type(exc).__name__}: {msg[:300]}"],
                impact=[
                    "Temuan material weakness dalam SOX audit.",
                    "Auditor akan melaporkan defisiensi ke audit committee.",
                ],
                suggested_fix=(
                    "1. Periksa compliance/sox_control_tester.py untuk control yang gagal. "
                    "2. Identifikasi dan perbaiki control deficiency. "
                    "3. Dokumentasikan remediation plan di compliance/deficiency_tracker.py."
                ),
                raw_error=msg, confidence=0.9,
            )
        return RCAResult(
            severity=Severity.CRITICAL, category=Category.SECURITY,
            error_code=ErrorCode.ERP_VALIDATION,
            root_cause=f"Compliance violation: {type(exc).__name__}: {msg[:200]}",
            evidence=[f"{msg[:300]}"],
            impact=["Potensi pelanggaran regulasi — tindakan korektif segera diperlukan."],
            suggested_fix="Periksa compliance/ untuk detail aturan yang dilanggar.",
            raw_error=msg, confidence=0.8,
        )


class AuditIntegrityRule(RCARule):
    """Deteksi error dari audit/ — tamper detection, hash chain corruption."""
    _AUDIT_PATTERN = re.compile(
        r"(AuditException|TamperDetected|HashChainCorrupted|"
        r"ImmutableEventViolation|ForensicReplayError|"
        r"audit.*hash.*mismatch|event.*tampered|"
        r"hash.*chain.*broken|audit.*log.*corrupted|"
        r"tamper.*alert|forensic.*replay.*failed)",
        re.I,
    )

    def __init__(self) -> None:
        super().__init__(priority=195, category=Category.SECURITY, name="AuditIntegrityRule")

    def match(self, exc, frames, context) -> bool:
        if self._AUDIT_PATTERN.search(str(exc)):
            return True
        return any("audit/" in f.filename.replace("\\","/").lower() for f in frames)

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg = str(exc)
        is_tamper = bool(re.search(r"tamper|TamperDetected", msg, re.I))
        is_hash   = bool(re.search(r"hash.*chain|HashChain.*corrupt", msg, re.I))
        return RCAResult(
            severity=Severity.FATAL, category=Category.SECURITY,
            error_code=ErrorCode.PERMISSION_DENIED,
            root_cause=(
                "TAMPER TERDETEKSI — audit log dimanipulasi!"
                if is_tamper else
                "Hash chain audit rusak — kemungkinan data dimodifikasi di luar sistem."
                if is_hash else
                f"Audit integrity violation: {type(exc).__name__}: {msg[:200]}"
            ),
            evidence=[f"Audit error: {type(exc).__name__}: {msg[:300]}"],
            impact=[
                "🚨 KRITIS: Integritas audit trail tidak bisa dijamin.",
                "Laporan keuangan berpotensi tidak bisa dipercaya.",
                "Wajib lapor ke Board of Directors dan External Auditor.",
                "Forensic investigation oleh pihak independen mungkin diperlukan.",
            ],
            suggested_fix=(
                "🚨 TINDAKAN DARURAT: "
                "1. Hentikan semua operasi tulis ke sistem. "
                "2. Preserve semua log file — jangan hapus apapun. "
                "3. Jalankan audit/forensic_replayer.py untuk reconstruct timeline. "
                "4. Gunakan audit/hash_chain_builder.py untuk verifikasi chain. "
                "5. Hubungi Internal Audit dan Legal segera. "
                "6. Pertimbangkan blockchain notarization via "
                "   audit/regulatory_attestation_signer.py."
            ),
            raw_error=msg, confidence=0.98,
        )


class CoretaxDJPRule(RCARule):
    """Deteksi error dari adapters/coretax_djp/ — integrasi DJP Indonesia."""
    _CORETAX_PATTERN = re.compile(
        r"(CoretaxException|CoretaxAPIError|OAuth2.*DJP|DJP.*OAuth|"
        r"FakturPajak.*error|NTPNInvalid|NSFP.*habis|"
        r"SPT.*submission.*failed|e.Bupot.*error|eMeterai.*error|"
        r"coretax.*timeout|DJP.*server.*error|"
        r"nomor.seri.faktur.*habis|NSFPExhausted|"
        r"efaktur.*reject|spt.*masa.*error|"
        r"certificate.*DJP.*expired|signature.*DJP)",
        re.I,
    )

    def __init__(self) -> None:
        super().__init__(priority=172, category=Category.INFRASTRUCTURE, name="CoretaxDJPRule")

    def match(self, exc, frames, context) -> bool:
        if self._CORETAX_PATTERN.search(str(exc)):
            return True
        if any(k in type(exc).__name__ for k in ("Coretax", "DJP", "Faktur", "NTPN", "NSFP")):
            return True
        return any("coretax_djp" in f.filename.replace("\\","/").lower() for f in frames)

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg = str(exc)

        if re.search(r"NSFP.*habis|NSFPExhausted|nomor.seri.faktur.*habis", msg, re.I):
            return RCAResult(
                severity=Severity.FATAL, category=Category.INFRASTRUCTURE,
                error_code=ErrorCode.ERP_VALIDATION,
                root_cause="NSFP (Nomor Seri Faktur Pajak) habis — tidak bisa menerbitkan e-Faktur.",
                evidence=[f"NSFP Error: {msg[:300]}"],
                impact=[
                    "🚨 Penjualan TIDAK BISA diterbitkan faktur pajak sampai NSFP diisi ulang.",
                    "Potensi denda keterlambatan penerbitan faktur (max 2% dari DPP).",
                ],
                suggested_fix=(
                    "1. SEGERA request NSFP tambahan ke DJP Coretax portal. "
                    "2. Kelola stok NSFP di adapters/coretax_djp/nsfp_manager.py. "
                    "3. Set alert ketika NSFP < 100 nomor tersisa."
                ),
                raw_error=msg, confidence=0.97,
            )

        if re.search(r"NTPNInvalid|NTPN.*invalid|NTPN.*tidak.valid", msg, re.I):
            return RCAResult(
                severity=Severity.CRITICAL, category=Category.INFRASTRUCTURE,
                error_code=ErrorCode.ERP_VALIDATION,
                root_cause="NTPN (Nomor Transaksi Penerimaan Negara) tidak valid — konfirmasi pembayaran pajak gagal.",
                evidence=[f"NTPN Error: {msg[:300]}"],
                impact=[
                    "Pembayaran pajak tidak bisa dikonfirmasi di sistem DJP.",
                    "SPT tidak bisa disubmit tanpa NTPN yang valid.",
                ],
                suggested_fix=(
                    "1. Verifikasi NTPN di adapters/coretax_djp/ntpn_validator.py. "
                    "2. Cek status pembayaran di sistem bank/billing pembayaran pajak. "
                    "3. Hubungi KPP jika NTPN tidak muncul dalam 1x24 jam."
                ),
                raw_error=msg, confidence=0.95,
            )

        if re.search(r"OAuth2|oauth.*token.*expired|DJP.*auth", msg, re.I):
            return RCAResult(
                severity=Severity.HIGH, category=Category.INFRASTRUCTURE,
                error_code=ErrorCode.ERP_VALIDATION,
                root_cause="OAuth2 token DJP Coretax expired atau invalid.",
                evidence=[f"Auth Error: {msg[:300]}"],
                impact=["Semua operasi Coretax API tidak bisa dilakukan sampai re-auth."],
                suggested_fix=(
                    "1. Refresh token di adapters/coretax_djp/api_oauth2_client.py. "
                    "2. Periksa expiry time token dan implementasikan auto-refresh. "
                    "3. Pastikan certificate DJP belum expired."
                ),
                raw_error=msg, confidence=0.92,
            )

        return RCAResult(
            severity=Severity.HIGH, category=Category.INFRASTRUCTURE,
            error_code=ErrorCode.ERP_VALIDATION,
            root_cause=f"Coretax DJP API error: {type(exc).__name__}: {msg[:200]}",
            evidence=[f"{msg[:300]}"],
            impact=["Integrasi perpajakan dengan DJP terganggu."],
            suggested_fix=(
                "Periksa adapters/coretax_djp/coretax_exceptions.py. "
                "Monitor di adapters/coretax_djp/health_dashboard.py."
            ),
            raw_error=msg, confidence=0.78,
        )


class SecurityHardeningRule(RCARule):
    """Deteksi error dari security_hardening/ dan infrastructure/security/."""
    _SEC_PATTERN = re.compile(
        r"(SecurityException|EncryptionFailed|DecryptionFailed|"
        r"HSMError|PKCSError|KeyVaultError|SigningFailed|"
        r"CertificateExpired|TLSHandshakeFailed|"
        r"HashiCorpVault.*error|encryption.*key.*not.*found|"
        r"private.*key.*unavailable|signature.*verification.*failed|"
        r"security.*hardening.*violation)",
        re.I,
    )

    def __init__(self) -> None:
        super().__init__(priority=188, category=Category.SECURITY, name="SecurityHardeningRule")

    def match(self, exc, frames, context) -> bool:
        if self._SEC_PATTERN.search(str(exc)):
            return True
        return any(
            any(k in f.filename.replace("\\","/").lower()
                for k in ("security_hardening", "security/security", "hsm_pkcs", "key_vault"))
            for f in frames
        )

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg = str(exc)
        if re.search(r"CertificateExpired|TLS.*handshake|certificate.*expired", msg, re.I):
            return RCAResult(
                severity=Severity.FATAL, category=Category.SECURITY,
                error_code=ErrorCode.PERMISSION_DENIED,
                root_cause="Certificate TLS expired — koneksi aman tidak bisa dibuat.",
                evidence=[f"{type(exc).__name__}: {msg[:300]}"],
                impact=["Seluruh komunikasi HTTPS/API tidak bisa dilakukan."],
                suggested_fix=(
                    "1. Renew certificate segera. "
                    "2. Set alert 30 hari sebelum expiry di infrastructure/telemetry/. "
                    "3. Gunakan Let's Encrypt auto-renewal atau Vault PKI secrets engine."
                ),
                raw_error=msg, confidence=0.95,
            )
        if re.search(r"HSM|PKCS|SigningFailed|signature.*fail", msg, re.I):
            return RCAResult(
                severity=Severity.FATAL, category=Category.SECURITY,
                error_code=ErrorCode.PERMISSION_DENIED,
                root_cause="HSM/PKCS11 signing gagal — dokumen tidak bisa ditandatangani secara digital.",
                evidence=[f"{type(exc).__name__}: {msg[:300]}"],
                impact=[
                    "e-Faktur, SPT, dan dokumen legal tidak bisa di-sign.",
                    "Submission ke DJP tidak bisa dilakukan.",
                ],
                suggested_fix=(
                    "1. Periksa koneksi ke HSM di adapters/secondary_impl/hsm_pkcs11_signing_adapter.py. "
                    "2. Pastikan HSM token tidak terkunci (PIN error). "
                    "3. Cek slot dan certificate di HSM."
                ),
                raw_error=msg, confidence=0.9,
            )
        if re.search(r"KeyVault|HashiCorp|encryption.*key|private.*key", msg, re.I):
            return RCAResult(
                severity=Severity.FATAL, category=Category.SECURITY,
                error_code=ErrorCode.PERMISSION_DENIED,
                root_cause="Encryption key tidak bisa diambil dari Key Vault.",
                evidence=[f"{type(exc).__name__}: {msg[:300]}"],
                impact=["Data sensitif tidak bisa di-encrypt/decrypt."],
                suggested_fix=(
                    "1. Periksa koneksi ke HashiCorp Vault: adapters/secondary_impl/hashicorp_vault_adapter.py. "
                    "2. Pastikan Vault service running dan unsealed. "
                    "3. Cek policy Vault untuk service account yang digunakan."
                ),
                raw_error=msg, confidence=0.9,
            )
        return RCAResult(
            severity=Severity.CRITICAL, category=Category.SECURITY,
            error_code=ErrorCode.PERMISSION_DENIED,
            root_cause=f"Security error: {type(exc).__name__}: {msg[:200]}",
            evidence=[f"{msg[:300]}"],
            impact=["Operasi keamanan gagal — data atau sistem mungkin tidak terlindungi."],
            suggested_fix=(
                "Periksa security_hardening/ dan infrastructure/security/security_exceptions.py."
            ),
            raw_error=msg, confidence=0.8,
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════════

_PROJECT_RULES: list[RCARule] = [
    AxiomViolationRule(),
    ConstitutionViolationRule(),
    AuditIntegrityRule(),
    KernelGuardViolationRule(),
    SecurityHardeningRule(),
    InfrastructureDatabaseRule(),
    BootstrapDIRule(),
    MessageBrokerRule(),
    SagaOrchestrationRule(),
    CoretaxDJPRule(),
    PolicyEngineRule(),
    ComplianceRule(),
    CachingRule(),
]


def register_all(engine: RCAEngine) -> int:
    """Daftarkan semua project-specific rules ke RCAEngine."""
    registered = 0
    for rule in _PROJECT_RULES:
        try:
            engine.register_rule(rule)
            registered += 1
            _logger.debug("Registered rule: %s (priority=%d)", rule.name, rule.priority)
        except Exception as exc:
            _logger.warning("Gagal register rule %s: %s", rule.name, exc)
    _logger.info(
        "rca_project_rules: %d/%d project rules registered",
        registered, len(_PROJECT_RULES)
    )
    return registered


# ═══════════════════════════════════════════════════════════════════════════════
#  SELF-TEST
# ═══════════════════════════════════════════════════════════════════════════════

def self_test_project(verbose: bool = True) -> bool:
    """Uji semua project-specific rules dengan exception nyata dari proyek ini."""
    # Gunakan import yang benar
    from checker.core.rca import get_engine, reset_engine

    reset_engine()
    engine = get_engine()
    register_all(engine)

    passed = failed = 0

    def check(name: str, cond: bool, got: str = "") -> None:
        nonlocal passed, failed
        if cond:
            if verbose:
                print(f"  ✅ {name}")
            passed += 1
        else:
            if verbose:
                print(f"  ❌ {name}" + (f": {got}" if got else ""))
            failed += 1

    if verbose:
        print(f"\nRunning RCA Project Rules self-test v{__version__}…")
        total_rules = engine.stats()["engine"]["rule_count"]
        print(f"  Total rules terdaftar: {total_rules}\n")

    # ── Axiom Violations ──────────────────────────────────────────────────────
    try:
        raise ValueError("AxiomViolation: double entry debit credit unbalanced — total debit 1500 != total kredit 1000")
    except Exception as e:
        r = engine.analyze(e)
        check("AxiomViolationRule — double entry unbalanced (FATAL)",
              r.severity == Severity.FATAL and "ouble" in r.root_cause, str(r.root_cause[:80]))

    try:
        raise RuntimeError("ImmutabilityViolation: posted journal entry cannot be modified after posting")
    except Exception as e:
        r = engine.analyze(e)
        check("AxiomViolationRule — immutability violation (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    try:
        raise RuntimeError("AccrualBasisViolation: revenue recognition before performance obligation satisfied")
    except Exception as e:
        r = engine.analyze(e)
        check("AxiomViolationRule — accrual basis (CRITICAL)",
              r.severity in (Severity.FATAL, Severity.CRITICAL), str(r.root_cause[:80]))

    # ── Constitution ──────────────────────────────────────────────────────────
    try:
        raise RuntimeError("ConstitutionViolation: ForbiddenState — negative equity not allowed by supreme law")
    except Exception as e:
        r = engine.analyze(e)
        check("ConstitutionViolationRule — forbidden state (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    # ── Kernel Guards ─────────────────────────────────────────────────────────
    try:
        raise PermissionError("PeriodLockViolation: fiscal period 2024-12 is locked and closed — posting not allowed")
    except Exception as e:
        r = engine.analyze(e)
        check("KernelGuardViolationRule — period lock (CRITICAL)",
              r.severity in (Severity.FATAL, Severity.CRITICAL), str(r.root_cause[:80]))

    try:
        raise PermissionError("SodViolation: same user cannot create and approve — four eyes principle violated")
    except Exception as e:
        r = engine.analyze(e)
        check("KernelGuardViolationRule — SOD violation (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    try:
        raise ValueError("BudgetExhausted: transaksi melebihi anggaran department Marketing Q4 2024")
    except Exception as e:
        r = engine.analyze(e)
        check("KernelGuardViolationRule — budget exhausted",
              "dget" in r.root_cause or r.severity == Severity.HIGH, str(r.root_cause[:80]))

    try:
        raise PermissionError("AMLFlaggedTransaction: transaksi mencurigakan terdeteksi — AML risk score 92/100")
    except Exception as e:
        r = engine.analyze(e)
        check("KernelGuardViolationRule — AML flagged (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    try:
        raise PermissionError("SystemFrozenError: sistem ERP dibekukan oleh emergency freeze protocol")
    except Exception as e:
        r = engine.analyze(e)
        check("KernelGuardViolationRule — emergency freeze (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    try:
        raise PermissionError("FraudPatternDetected: pola kecurangan terdeteksi pada transaksi AP #INV-001")
    except Exception as e:
        r = engine.analyze(e)
        check("KernelGuardViolationRule — fraud pattern (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    # ── Database ──────────────────────────────────────────────────────────────
    try:
        raise Exception("DatabaseException: deadlock detected while inserting into journal_line_table")
    except Exception as e:
        r = engine.analyze(e)
        check("InfrastructureDatabaseRule — deadlock",
              "eadlock" in r.root_cause, str(r.root_cause[:80]))

    try:
        raise Exception("duplicate key value violates unique constraint 'uq_journal_number'")
    except Exception as e:
        r = engine.analyze(e)
        check("InfrastructureDatabaseRule — unique constraint",
              r.severity == Severity.HIGH, str(r.root_cause[:80]))

    try:
        raise Exception("remaining connection slots are reserved — too many connections to database 'erp_db'")
    except Exception as e:
        r = engine.analyze(e)
        check("InfrastructureDatabaseRule — connection pool exhausted (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    try:
        raise Exception("relation 'journal_header_table' does not exist — migration pending")
    except Exception as e:
        r = engine.analyze(e)
        check("InfrastructureDatabaseRule — migration pending (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    # ── Message Broker ────────────────────────────────────────────────────────
    try:
        raise Exception("MessagePublishFailed: kafka dead letter queue full — event JournalPostedEvent not sent")
    except Exception as e:
        r = engine.analyze(e)
        check("MessageBrokerRule — dead letter queue",
              "ead.letter" in r.root_cause.lower() or r.severity == Severity.CRITICAL,
              str(r.root_cause[:80]))

    try:
        raise Exception("OutboxRelay stuck — outbox table has 150 unprocessed events older than 10 minutes")
    except Exception as e:
        r = engine.analyze(e)
        check("MessageBrokerRule — outbox stuck",
              "outbox" in r.root_cause.lower() or r.severity == Severity.HIGH,
              str(r.root_cause[:80]))

    # ── Saga ──────────────────────────────────────────────────────────────────
    try:
        raise RuntimeError("SagaStepFailed: procurement_saga step 3 (AP Invoice creation) failed — rollback initiated")
    except Exception as e:
        r = engine.analyze(e)
        check("SagaOrchestrationRule — procurement saga step failed",
              r.severity in (Severity.FATAL, Severity.CRITICAL), str(r.root_cause[:80]))

    try:
        raise RuntimeError("SagaCompensationFailed: coretax_submission_saga compensation failed — system in inconsistent state")
    except Exception as e:
        r = engine.analyze(e)
        check("SagaOrchestrationRule — saga compensation failed (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    # ── DI / Bootstrap ────────────────────────────────────────────────────────
    try:
        raise RuntimeError("DIException: circular dependency detected — ServiceA depends on ServiceB which depends on ServiceA")
    except Exception as e:
        r = engine.analyze(e)
        check("BootstrapDIRule — circular DI dependency (FATAL)",
              r.severity == Severity.FATAL and "ircular" in r.root_cause, str(r.root_cause[:80]))

    try:
        raise RuntimeError("ServiceNotRegistered: cannot resolve service IAccountRepositoryPort — not bound in ioc_container")
    except Exception as e:
        r = engine.analyze(e)
        check("BootstrapDIRule — service not registered (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    # ── Policy Engine ─────────────────────────────────────────────────────────
    try:
        raise ValueError("IFRS15 violation: revenue recognized before performance obligation satisfied for contract C-001")
    except Exception as e:
        r = engine.analyze(e)
        check("PolicyEngineRule — IFRS 15 revenue recognition",
              r.severity in (Severity.FATAL, Severity.CRITICAL), str(r.root_cause[:80]))

    try:
        raise ValueError("IAS36 impairment test required — goodwill carrying amount exceeds recoverable amount")
    except Exception as e:
        r = engine.analyze(e)
        check("PolicyEngineRule — IAS 36 impairment",
              r.severity in (Severity.FATAL, Severity.CRITICAL), str(r.root_cause[:80]))

    try:
        raise ValueError("PSAK25 error: koreksi periode lalu ditemukan — restatement diperlukan untuk laporan 2023")
    except Exception as e:
        r = engine.analyze(e)
        check("PolicyEngineRule — PSAK 25 prior period error",
              r.severity in (Severity.FATAL, Severity.CRITICAL), str(r.root_cause[:80]))

    try:
        raise ValueError("PajakException: DJP response error — e.Bupot PPh 23 gagal disubmit ke Coretax")
    except Exception as e:
        r = engine.analyze(e)
        check("PolicyEngineRule — Indonesian tax error",
              r.severity in (Severity.FATAL, Severity.CRITICAL), str(r.root_cause[:80]))

    # ── Compliance ────────────────────────────────────────────────────────────
    try:
        raise RuntimeError("GDPRViolation: data privacy violation — customer PII retained beyond 7 year limit")
    except Exception as e:
        r = engine.analyze(e)
        check("ComplianceRule — GDPR violation (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    try:
        raise RuntimeError("SanctionListMatch: entity 'PT XYZ' matched OFAC SDN list — transaction BLOCKED")
    except Exception as e:
        r = engine.analyze(e)
        check("ComplianceRule — sanction list hit (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    try:
        raise RuntimeError("SOXControlFailed: sox control test failed — AP payment approval bypass detected")
    except Exception as e:
        r = engine.analyze(e)
        check("ComplianceRule — SOX control failure (CRITICAL)",
              r.severity in (Severity.FATAL, Severity.CRITICAL), str(r.root_cause[:80]))

    # ── Audit Integrity ───────────────────────────────────────────────────────
    try:
        raise RuntimeError("TamperDetected: audit log hash chain broken at event #4521 — data may have been modified")
    except Exception as e:
        r = engine.analyze(e)
        check("AuditIntegrityRule — tamper detected (FATAL)",
              r.severity == Severity.FATAL and len(r.impact) >= 3, str(r.root_cause[:80]))

    # ── Coretax DJP ───────────────────────────────────────────────────────────
    try:
        raise Exception("NSFPExhausted: nomor seri faktur pajak habis — tidak bisa menerbitkan e-Faktur baru")
    except Exception as e:
        r = engine.analyze(e)
        check("CoretaxDJPRule — NSFP habis (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    try:
        raise Exception("NTPNInvalid: NTPN 0000000000000000 tidak valid — konfirmasi pembayaran pajak gagal")
    except Exception as e:
        r = engine.analyze(e)
        check("CoretaxDJPRule — NTPN tidak valid (CRITICAL)",
              r.severity in (Severity.FATAL, Severity.CRITICAL), str(r.root_cause[:80]))

    # ── Security ──────────────────────────────────────────────────────────────
    try:
        raise RuntimeError("CertificateExpired: TLS certificate for api.coretax.pajak.go.id expired on 2024-01-15")
    except Exception as e:
        r = engine.analyze(e)
        check("SecurityHardeningRule — certificate expired (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    try:
        raise RuntimeError("HSMError: PKCS11 signing failed — HSM token locked after 3 PIN attempts")
    except Exception as e:
        r = engine.analyze(e)
        check("SecurityHardeningRule — HSM signing failed (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    # ── Caching ───────────────────────────────────────────────────────────────
    try:
        raise Exception("DistributedLockTimeout: lock acquisition failed for 'journal:2024-001' after 5s — Redis timeout")
    except Exception as e:
        r = engine.analyze(e)
        check("CachingRule — distributed lock timeout",
              r.severity == Severity.HIGH, str(r.root_cause[:80]))

    # ── Rule stats ────────────────────────────────────────────────────────────
    stats    = engine.stats()
    rule_cnt = stats["engine"]["rule_count"]
    check("Total rules terdaftar ≥ 30 (generic + project)", rule_cnt >= 30, str(rule_cnt))

    if verbose:
        print()
        print(f"Project Rules self-test: {passed} passed, {failed} failed "
              f"({'✅ ALL PASS' if failed == 0 else '❌ SOME FAILED'})")
        print()
        print(f"Total rules aktif di engine: {rule_cnt}")
        print("  — Generic rules (rca.py) : ~18")
        print(f"  — Project rules (ini)    : {len(_PROJECT_RULES)}")

    return failed == 0


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    ok = self_test_project(verbose=True)
    sys.exit(0 if ok else 1)
