# infrastructure/persistence_orm/__init__.py
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import Column, DateTime, ForeignKey, Table
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from infrastructure.persistence_orm.base_model import Base, TimestampMixin

logger = logging.getLogger(__name__)

# ============================================================================
# 1. LEGAL ENTITY (harus pertama agar FK ke legal_entity bisa di-resolve)
# ============================================================================
from infrastructure.persistence_orm.legal_entity_table import LegalEntityTable

# ============================================================================
# 2. IAM TABLES (user, role, permission, session, login attempt)
# ============================================================================
from infrastructure.persistence_orm.iam_user_table import (
    IAMPermissionTable,
    IAMRoleTable,
    IAMSessionTable,
    IAMUserTable,
    LoginAttemptTable,
    iam_role_permission,
    iam_user_role,
)

# ============================================================================
# 3. JUNCTION TABLE: iam_user_legal_entity
# (didefinisikan di sini setelah legal_entity dan iam_user siap)
# ============================================================================
iam_user_legal_entity = Table(
    "iam_user_legal_entity",
    Base.metadata,
    Column("user_id", PGUUID(as_uuid=True), ForeignKey("iam_user.id"), primary_key=True),
    Column("legal_entity_id", PGUUID(as_uuid=True), ForeignKey("legal_entity.id"), primary_key=True),
    Column("assigned_at", DateTime(timezone=True), server_default="now()"),
    Column("assigned_by", PGUUID(as_uuid=True), nullable=True),
    extend_existing=True,
)

# ============================================================================
# 4. PROJECTION / READ MODELS
# ============================================================================
from infrastructure.persistence_orm.projection_read_models import (
    ProjectionARAgingTable,
    ProjectionAPAgingTable,
    ProjectionCoretaxDashboardTable,
    ProjectionFinancialRatiosTable,
    ProjectionGLTable,
    ProjectionKpiAlerterTable,
    ProjectionPPHSummaryTable,
    ProjectionPPNSettlementTable,
    ProjectionProfitabilitySegmentTable,
    ProjectionTrend12MonthTable,
    ProjectionTrialBalanceTable,
    ProjectionVarianceAnalysisTable,
)

# ============================================================================
# 5. SAGA ORCHESTRATION
# ============================================================================
from infrastructure.persistence_orm.saga_orchestration_table import (
    SagaEventTable,
    SagaInstanceTable,
    SagaLockTable,
    SagaStepLogTable,
)

# ============================================================================
# 6. CORETAX
# ============================================================================
from infrastructure.persistence_orm.coretax_faktur_keluaran_table import CoretaxFakturKeluaranTable
from infrastructure.persistence_orm.coretax_faktur_masukan_table import CoretaxFakturMasukanTable

# ============================================================================
# 7. MANUFACTURING
# ============================================================================
from infrastructure.persistence_orm.manufacturing_routing_table import RoutingTable
from infrastructure.persistence_orm.routing_step_table import RoutingStepTable
from infrastructure.persistence_orm.manufacturing_wip_table import WorkInProcessTable

# ============================================================================
# 8. PAYROLL
# ============================================================================
from infrastructure.persistence_orm.payroll_detail_table import (
    PayrollAdjustmentTable,
    PayrollDetailTable,
    SalaryStructureTable,
)

# ============================================================================
# 9. DELIVERY ORDER
# ============================================================================
from infrastructure.persistence_orm.delivery_order_table import DeliveryOrderLineTable, DeliveryOrderTable

# ============================================================================
# 10. UMKM
# ============================================================================
from infrastructure.persistence_orm.umkm_journal_table import UmkmJournalTable

# ============================================================================
# 11. EQUITY
# ============================================================================
from infrastructure.persistence_orm.equity_tables import (
    CapitalContributionTable,
    DividendDeclarationTable,
    RetainedEarningsHistoryTable,
)

# ============================================================================
# 12. TAX SETTLEMENT
# ============================================================================
from infrastructure.persistence_orm.tax_settlement_table import PphWithholdingSummaryTable, PpnSettlementTable

# ============================================================================
# 13. GOODS RECEIPT LINE & SALES ORDER LINE
# ============================================================================
from infrastructure.persistence_orm.goods_receipt_line_table import GoodsReceiptLineTable
from infrastructure.persistence_orm.sales_order_line_table import SalesOrderLineTable


# ============================================================================
# DAFTAR SEMUA MODEL UNTUK DIEKSPOR
# ============================================================================
__all__ = [
    # IAM
    "IAMUserTable",
    "IAMRoleTable",
    "IAMPermissionTable",
    "IAMSessionTable",
    "LoginAttemptTable",
    "iam_user_role",
    "iam_role_permission",
    "iam_user_legal_entity",  # penting untuk diekspor
    # Projection
    "ProjectionGLTable",
    "ProjectionTrialBalanceTable",
    "ProjectionARAgingTable",
    "ProjectionAPAgingTable",
    "ProjectionPPNSettlementTable",
    "ProjectionPPHSummaryTable",
    "ProjectionCoretaxDashboardTable",
    "ProjectionTrend12MonthTable",
    "ProjectionVarianceAnalysisTable",
    "ProjectionProfitabilitySegmentTable",
    "ProjectionFinancialRatiosTable",
    "ProjectionKpiAlerterTable",
    # Saga
    "SagaInstanceTable",
    "SagaStepLogTable",
    "SagaLockTable",
    "SagaEventTable",
    # Coretax
    "CoretaxFakturKeluaranTable",
    "CoretaxFakturMasukanTable",
    # Manufacturing
    "RoutingTable",
    "RoutingStepTable",
    "WorkInProcessTable",
    # Payroll
    "SalaryStructureTable",
    "PayrollDetailTable",
    "PayrollAdjustmentTable",
    # Delivery Order
    "DeliveryOrderTable",
    "DeliveryOrderLineTable",
    # UMKM
    "UmkmJournalTable",
    # Equity
    "CapitalContributionTable",
    "DividendDeclarationTable",
    "RetainedEarningsHistoryTable",
    # Tax Settlement
    "PpnSettlementTable",
    "PphWithholdingSummaryTable",
    # Goods Receipt Line & Sales Order Line
    "GoodsReceiptLineTable",
    "SalesOrderLineTable",
    # Legal Entity
    "LegalEntityTable",
]

logger.info(f"Loaded {len(__all__)} ORM models from persistence_orm package.")