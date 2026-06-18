# __init__.py - Complete exports for application.workflows package

from __future__ import annotations

"""
Package: application.workflows

Business workflows for end-to-end processes.

This package provides complete workflow implementations for:
- Audit forensic reconstruction (event sourcing)
- Inventory to COGS calculation
- Manufacturing cost flow
- Payroll to General Ledger
- Procurement to Accounts Payable
- Project billing and revenue recognition
- Sales to Accounts Receivable
- UMKM simplified accounting

All workflows use saga pattern for distributed transactions and provide:
- Command-based execution
- Compensation on failure
- Audit logging
- Statistics tracking
"""

__version__ = "2.0.0"

# Audit Forensic Reconstruction
from application.workflows.audit_forensic_reconstruction import (
    AuditForensicReconstructionCommand,
    AuditForensicReconstructionWorkflow,
    ForensicReconstructionResult,
    create_audit_forensic_reconstruction_workflow,
)

# Inventory to COGS
from application.workflows.inventory_to_cogs import (
    COGSCalculationItem,
    InventoryToCOGSCommand,
    InventoryToCOGSResult,
    InventoryToCOGSWorkflow,
    create_inventory_to_cogs_workflow,
)

# Manufacturing Cost Flow
from application.workflows.manufacturing_cost_flow import (
    ManufacturingCostFlowCommand,
    ManufacturingCostFlowResult,
    ManufacturingCostFlowWorkflow,
    create_manufacturing_cost_flow_workflow,
)

# Payroll to GL
from application.workflows.payroll_to_gl_full import (
    PayrollToGLFullCommand,
    PayrollToGLFullWorkflow,
    PayrollWorkflowResult,
    create_payroll_to_gl_full_workflow,
)

# Procurement to AP
from application.workflows.procurement_to_ap_full import (
    ProcurementToAPFullCommand,
    ProcurementToAPFullWorkflow,
    ProcurementWorkflowResult,
    create_procurement_to_ap_full_workflow,
)

# Project Billing
from application.workflows.project_billing_poc import (
    ProjectBillingCommand,
    ProjectBillingResult,
    ProjectBillingWorkflow,
    create_project_billing_workflow,
)

# Sales to AR
from application.workflows.sales_to_ar_full import (
    SalesToARFullCommand,
    SalesToARFullWorkflow,
    SalesWorkflowResult,
    create_sales_to_ar_full_workflow,
)

# UMKM Simplified
from application.workflows.umkm_simplified import (
    TransactionCategory,
    UMKMWorkflow,
    UMKMWorkflowCommand,
    UMKMWorkflowResult,
    create_umkm_workflow,
)

__all__ = [
    # Version
    "__version__",
    # Audit Forensic Reconstruction
    "AuditForensicReconstructionCommand",
    "AuditForensicReconstructionWorkflow",
    "ForensicReconstructionResult",
    "create_audit_forensic_reconstruction_workflow",
    # Inventory to COGS
    "COGSCalculationItem",
    "InventoryToCOGSCommand",
    "InventoryToCOGSResult",
    "InventoryToCOGSWorkflow",
    "create_inventory_to_cogs_workflow",
    # Manufacturing Cost Flow
    "ManufacturingCostFlowCommand",
    "ManufacturingCostFlowResult",
    "ManufacturingCostFlowWorkflow",
    "create_manufacturing_cost_flow_workflow",
    # Payroll to GL
    "PayrollToGLFullCommand",
    "PayrollToGLFullWorkflow",
    "PayrollWorkflowResult",
    "create_payroll_to_gl_full_workflow",
    # Procurement to AP
    "ProcurementToAPFullCommand",
    "ProcurementToAPFullWorkflow",
    "ProcurementWorkflowResult",
    "create_procurement_to_ap_full_workflow",
    # Project Billing
    "ProjectBillingCommand",
    "ProjectBillingResult",
    "ProjectBillingWorkflow",
    "create_project_billing_workflow",
    # Sales to AR
    "SalesToARFullCommand",
    "SalesToARFullWorkflow",
    "SalesWorkflowResult",
    "create_sales_to_ar_full_workflow",
    # UMKM Simplified
    "TransactionCategory",
    "UMKMWorkflow",
    "UMKMWorkflowCommand",
    "UMKMWorkflowResult",
    "create_umkm_workflow",
]
